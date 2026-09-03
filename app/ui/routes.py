"""
Real-time Dashboard UI Module
- FastAPI routes untuk dashboard
- WebSocket untuk real-time updates
- HTML/CSS/JS frontend
"""
import csv
import hmac
import io
import json
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import database as app_database
from app.config import get_settings
from app.database import get_recent_signals, get_system_stats
from app.dashboard import AlertSystem, BacktestEngine
from app.runtime_settings import (
    SPECS_BY_KEY,
    build_settings_payload,
    defaults_from_env,
    encrypt_secret,
    is_encrypted,
    decrypt_secret,
    load_overrides,
    validate_value,
)
from app.security.hardening import signal_validator, penetration_tester, dependency_auditor
from app.ui.rate_limit import rate_limit_dependency, reset_all_limiters


def _effective_retention_days() -> int:
    """Hari retensi efektif (v2.6): override runtime dulu, fallback env.

    Dipakai endpoint retention agar panel dashboard menampilkan nilai
    yang sama dengan yang dipakai loop prune di main.py.
    """
    from app import runtime_settings as _rs
    env_days = get_settings().alert_history_retention_days
    return _rs.get_int("alert_history_retention_days", env_days)

router = APIRouter()

logger = logging.getLogger(__name__)

# Waktu proses dimulai - dipakai untuk metrik uptime di dashboard
_SERVICE_START_TIME = time.monotonic()

# Lazy singleton engines (dibuat saat pertama kali dipakai; reset_engines()
# dipakai test suite agar tiap test mulai dari state bersih)
_alert_system: Optional[AlertSystem] = None
_backtest_engine: Optional[BacktestEngine] = None

# v2.5: holder notifier (dipasang oleh main.initialize agar endpoint
# /api/telegram/* bisa memakai instance yang benar-benar berjalan).
# Token TIDAK pernah dikirim ke client - hanya status metadata.
_notifier: Optional[Any] = None

# v2.5: hasil prune terakhir (diisi oleh loop retensi di main.py atau
# endpoint manual POST /api/alerts/prune) untuk panel maintenance.
_last_prune: Optional[Dict[str, Any]] = None


def get_alert_system() -> AlertSystem:
    """Lazy singleton AlertSystem (tanpa load persistensi; sync aman dipakai
    di context non-async). Untuk memuat threshold tersimpan DB, pakai
    `await get_alert_system_async()` di endpoint."""
    global _alert_system
    if _alert_system is None:
        _alert_system = AlertSystem(app_database.db)
        _alert_system._load_default_rules()
    return _alert_system


async def get_alert_system_async() -> AlertSystem:
    """Lazy singleton AlertSystem + muat threshold tersimpan DB (v2.4).

    Load hanya dilakukan sekali per instance; perubahan lewat PUT tetap
    di-persist manual sehingga tidak perlu reload tiap request.
    """
    alert_system = get_alert_system()
    if not getattr(alert_system, "_persisted_loaded", False):
        await alert_system.load_persisted_rules()
        alert_system._persisted_loaded = True
    return alert_system


def get_backtest_engine() -> BacktestEngine:
    """Lazy singleton BacktestEngine."""
    global _backtest_engine
    if _backtest_engine is None:
        _backtest_engine = BacktestEngine(app_database.db)
    return _backtest_engine


def reset_engines() -> None:
    """Reset singleton engines (untuk testing)."""
    global _alert_system, _backtest_engine, _notifier, _last_prune
    _alert_system = None
    _backtest_engine = None
    _notifier = None
    _last_prune = None


def set_notifier(notifier: Any) -> None:
    """Pasang instance TelegramNotifier yang dipakai pipeline utama (v2.5)."""
    global _notifier
    _notifier = notifier


def get_notifier() -> Optional[Any]:
    """Ambil notifier yang terpasang (None bila belum di-initialize)."""
    return _notifier


def record_prune_result(at_iso: str, rows_deleted: int) -> None:
    """Simpan hasil prune terakhir untuk ditampilkan di panel retention."""
    global _last_prune
    _last_prune = {"at": at_iso, "rows": int(rows_deleted)}


class RuleUpdateRequest(BaseModel):
    """Body PUT /api/alerts/rules/{name}"""
    threshold: float = Field(ge=0, description="Nilai threshold baru (>= 0)")


class RuleImportItem(BaseModel):
    """Satu rule dalam body POST /api/alerts/rules/import (v2.7).

    Threshold divalidasi per-item (bukan 422 level batch) agar satu nilai
    jelek tidak menggagalkan import 10 rule lain.
    """
    name: str = Field(min_length=1, max_length=100)
    threshold: float


class RuleImportRequest(BaseModel):
    """Body POST /api/alerts/rules/import (v2.7)"""
    rules: List[RuleImportItem] = Field(min_length=1, max_length=100)


class BacktestRequest(BaseModel):
    """Body POST /api/backtest/{symbol}"""
    days: int = Field(default=7, ge=1, le=90, description="Periode lookback (1-90 hari)")
    volume_threshold: float = Field(
        default=300.0, ge=10, le=10000,
        description="Ambang volume spike %% (10-10000)",
    )


class PruneRequest(BaseModel):
    """Body opsional POST /api/alerts/prune (v2.5)"""
    days: Optional[int] = Field(
        default=None, ge=1, le=365,
        description="Retensi manual (hari). Default: pengaturan retention.",
    )


class SettingsUpdateRequest(BaseModel):
    """Body PUT /api/settings (v2.6): {updates: {key: value_str}}"""
    updates: Dict[str, str] = Field(
        description="Peta key -> nilai baru. Secret dikirim plaintext lalu "
                    "dienkripsi sebelum disimpan.",
    )

# Path template relatif terhadap file ini (bukan hard-coded /app)
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Store connected WebSocket clients
active_connections: List[WebSocket] = []


def _utc_now_iso() -> str:
    """Current UTC timestamp as ISO-8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()


async def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Opt-in API key auth untuk semua endpoint /api/*.

    Aturan:
    - Jika settings.dashboard_api_key TIDAK di-set (None) -> auth nonaktif
      (mode lokal/default, semua request diterima).
    - Jika di-set -> header X-API-Key wajib ada dan cocok (401 jika tidak).

    WebSocket dan halaman HTML tidak dilindungi (browser WS tidak bisa
    mengirim custom header); proteksi berfokus pada data API.
    """
    expected = get_settings().dashboard_api_key
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(str(x_api_key), str(expected)):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key header",
        )


# Dependensi standar untuk endpoint /api/*: auth opt-in + rate limit per-IP
# (didefinisikan setelah require_api_key agar referensinya valid)
API_DEPS = [Depends(require_api_key), Depends(rate_limit_dependency)]


async def broadcast_update(data: Dict[str, Any]):
    """Kirim update ke semua client WebSocket yang terhubung"""
    if not active_connections:
        return

    message = json.dumps(data, default=str)
    disconnected = []

    for connection in list(active_connections):
        try:
            await connection.send_text(message)
        except Exception:
            disconnected.append(connection)

    # Remove disconnected clients (hanya jika masih ada di list)
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Halaman utama dashboard"""
    # Signature baru Starlette: (request, name, context)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"title": "Crypto Oracle AI - Dashboard"},
    )


@router.get("/api/stats", dependencies=API_DEPS)
async def get_dashboard_stats():
    """API endpoint untuk statistik real-time"""
    try:
        # Ambil data dari database
        recent_signals = await get_recent_signals(limit=50)
        system_stats = await get_system_stats()
        
        # Hitung uptime riil proses (dalam jam)
        uptime_hours = round((time.monotonic() - _SERVICE_START_TIME) / 3600, 2)
        system_stats["uptime_hours"] = uptime_hours

        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "data": {
                "signals": recent_signals,
                "system": system_stats,
                "uptime": uptime_hours
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/security/audit", dependencies=API_DEPS)
async def security_audit():
    """Jalankan audit keamanan dan tampilkan hasil"""
    try:
        # Scan dependencies
        scan_results = await dependency_auditor.scan_dependencies()
        report = dependency_auditor.generate_audit_report(scan_results)

        # Run penetration tests
        pentest_results = await penetration_tester.run_security_tests()

        return {
            "status": "success",
            "audit": {
                "dependencies": scan_results,
                "report": report,
                "pentest": pentest_results
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/anomalies", dependencies=API_DEPS)
async def get_anomalies(limit: int = 50, symbol: str = None):
    """API endpoint untuk daftar anomali volume terbaru"""
    try:
        # Batasi limit agar aman dari abuse
        limit = max(1, min(limit, 500))
        anomalies = await app_database.db.get_recent_anomalies(symbol=symbol, limit=limit)
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "count": len(anomalies),
            "data": anomalies,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/export/signals.csv", dependencies=API_DEPS)
async def export_signals_csv(limit: int = 500):
    """Export sinyal terbaru sebagai file CSV"""
    try:
        limit = max(1, min(limit, 5000))
        signals = await get_recent_signals(limit=limit)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        # Header
        writer.writerow(["id", "symbol", "signal_type", "status", "timestamp", "message"])
        for s in signals:
            writer.writerow([
                s.get("id", ""),
                s.get("symbol", ""),
                s.get("signal_type", ""),
                s.get("status", ""),
                s.get("timestamp", ""),
                (s.get("message") or "").replace("\n", " "),
            ])
        buffer.seek(0)

        filename = f"signals_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/symbols", dependencies=API_DEPS)
async def get_symbols():
    """Ringkasan per-symbol (jumlah anomali, harga terakhir, rata-rata spike).

    Dipakai dashboard untuk Market Pulse panel dan filter dropdown.
    """
    try:
        summary = await app_database.db.get_symbol_summary()
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "count": len(summary),
            "data": summary,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/symbol/{symbol}", dependencies=API_DEPS)
async def get_symbol_detail(symbol: str, history_points: int = 120):
    """Detail lengkap satu symbol untuk modal dashboard:

    - aggregates dari get_symbol_summary (jika ada)
    - riwayat harga kronologis (lama -> baru) untuk chart besar
    - anomali terakhir symbol tsb

    404 bila symbol tidak dikenal (tidak ada summary/anomali/history).
    """
    try:
        symbol = symbol.upper().strip()
        history_points = max(10, min(history_points, 500))

        summary_list = await app_database.db.get_symbol_summary()
        summary = next(
            (s for s in summary_list if str(s.get("symbol", "")).upper() == symbol),
            None,
        )
        anomalies = await app_database.db.get_recent_anomalies(symbol=symbol, limit=50)
        history = await app_database.db.get_price_history(symbol, limit=history_points)

        if summary is None and not anomalies and not history:
            raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")

        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "symbol": symbol,
            "data": {
                "summary": summary,
                "anomalies": anomalies,
                "history": history,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/rules", dependencies=API_DEPS)
async def get_alert_rules():
    """Daftar alert rules (metadata + threshold) untuk panel konfigurasi UI.

    v2.4: threshold yang tersimpan di DB otomatis diterapkan saat load.
    """
    try:
        alert_system = await get_alert_system_async()
        rules = alert_system.get_rules()
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "count": len(rules),
            "data": rules,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.put("/api/alerts/rules/{name}", dependencies=API_DEPS)
async def update_alert_rule(name: str, body: RuleUpdateRequest):
    """Ubah threshold satu alert rule (hanya rule editable).

    v2.4: threshold juga di-persist ke tabel alert_rules sehingga
    survive restart (best-effort; flag 'persisted' di response).
    """
    try:
        alert_system = await get_alert_system_async()
        rule = alert_system.set_rule_threshold(name, body.threshold)
        persisted = await alert_system.persist_rule_threshold(name, body.threshold)
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "persisted": persisted,
            "data": rule,
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown rule: {name}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/rules/export", dependencies=API_DEPS)
async def export_alert_rules():
    """Export konfigurasi alert rules sebagai file JSON (v2.7).

    Response berupa attachment JSON (Content-Disposition) sehingga bisa
    langsung diunduh dari dashboard dan di-import ulang lewat
    POST /api/alerts/rules/import (mis. untuk backup/migrasi antar instans).
    """
    try:
        alert_system = await get_alert_system_async()
        rules = alert_system.get_rules()
        payload = {
            "kind": "zcapital.alert_rules",
            "version": "2.7",
            "exported_at": _utc_now_iso(),
            "count": len(rules),
            "rules": rules,
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return StreamingResponse(
            io.StringIO(json.dumps(payload, indent=2, default=str)),
            media_type="application/json",
            headers={
                "Content-Disposition":
                    f'attachment; filename="alert_rules_{stamp}.json"',
            },
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/api/alerts/rules/import", dependencies=API_DEPS)
async def import_alert_rules(body: RuleImportRequest):
    """Bulk import threshold alert rules dari JSON export (v2.7).

    Perilaku per-item (batch tetap sukses walau ada item bermasalah):
    - rule editable  -> threshold di-update + persist best-effort
    - rule unknown   -> status "unknown" (dilaporkan, bukan 404)
    - non-editable   -> status "not_editable"
    - threshold < 0 / non-finite -> status "invalid_threshold"
    """
    try:
        alert_system = await get_alert_system_async()
        results: List[Dict[str, Any]] = []
        updated = 0
        for item in body.rules:
            name = item.name.strip()
            if not name:
                results.append({"name": item.name, "status": "invalid_threshold"})
                continue
            if item.threshold != item.threshold or item.threshold in (
                float("inf"), float("-inf")
            ) or item.threshold < 0:
                results.append({"name": name, "status": "invalid_threshold"})
                continue
            try:
                rule = alert_system.set_rule_threshold(name, item.threshold)
            except KeyError:
                results.append({"name": name, "status": "unknown"})
                continue
            except ValueError:
                results.append({"name": name, "status": "not_editable"})
                continue
            persisted = await alert_system.persist_rule_threshold(
                name, item.threshold
            )
            updated += 1
            results.append({
                "name": name,
                "status": "updated",
                "threshold": rule["threshold"],
                "persisted": persisted,
            })
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "received": len(body.rules),
            "updated": updated,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/rule-stats", dependencies=API_DEPS)
async def get_alert_rule_stats(hours: int = 24):
    """Agregasi alert per-rule per-jam untuk audit sparkline (v2.7).

    Slot jam kosong diisi count 0 sehingga frontend bisa langsung
    menggambar bar chart tanpa interpolasi. Window dibatasi 1..168 jam
    (sparkline tidak butuh window setahun).
    """
    try:
        hours_f = max(1, min(int(hours), 168))
        rows = await app_database.db.get_alert_rule_stats(hours=hours_f)

        now_hour = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        per_rule: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            name = str(row.get("rule", ""))
            if not name:
                continue
            entry = per_rule.setdefault(
                name, {"rule": name, "total": 0, "last_fired": None,
                       "_sparse": {}}
            )
            count = int(row.get("count", 0) or 0)
            hour = row.get("hour")
            # Key epoch-detik agar robust terhadap perbedaan repr tz
            key = int(hour.timestamp()) if hasattr(hour, "timestamp") else None
            if key is None:
                continue
            entry["_sparse"][key] = entry["_sparse"].get(key, 0) + count
            entry["total"] += count

        data: List[Dict[str, Any]] = []
        for name, entry in per_rule.items():
            buckets = []
            last_ts = None
            for i in range(hours_f - 1, -1, -1):
                slot_dt = now_hour - timedelta(hours=i)
                key = int(slot_dt.timestamp())
                count = entry["_sparse"].get(key, 0)
                buckets.append({
                    "hour": slot_dt.isoformat(),
                    "count": count,
                })
                if count > 0:
                    last_ts = key
            data.append({
                "rule": name,
                "total": entry["total"],
                "last_fired": (
                    datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
                    if last_ts is not None else None
                ),
                "buckets": buckets,
            })
        data.sort(key=lambda x: (-x["total"], x["rule"]))
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "window_hours": hours_f,
            "count": len(data),
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/history", dependencies=API_DEPS)
async def get_alert_history(
    limit: int = 25,
    symbol: Optional[str] = None,
    hours: Optional[int] = None,
):
    """Riwayat alert yang pernah ter-trigger.

    v2.4: sumber utama kini tabel alert_history di DB (persisten, tahan
    restart). Bila DB gagal, fallback ke riwayat in-memory sejak proses
    start dengan flag "source" yang sesuai.
    v2.6: filter opsional `symbol` (exact) dan `hours` (jendela waktu)
    untuk click-to-filter dari heat map.
    """
    try:
        limit = max(1, min(limit, 200))
        symbol_f = (symbol or None) if symbol is None else str(symbol).strip().upper() or None
        hours_f = max(1, min(int(hours), 720)) if hours else None
        try:
            history = await app_database.db.get_alert_history(
                limit=limit, symbol=symbol_f, hours=hours_f
            )
            source = "database"
        except Exception as db_err:
            logger.warning(f"Alert history DB unavailable, using memory: {db_err}")
            history = get_alert_system().get_alert_history(limit=limit)
            source = "memory"
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "source": source,
            "count": len(history),
            "filters": {"symbol": symbol_f, "hours": hours_f},
            "data": history,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/heatmap", dependencies=API_DEPS)
async def get_alert_heatmap(hours: int = 24):
    """Agregasi alert per-symbol per-jam untuk heat map dashboard (v2.5).

    - hours di-clamp 6..168 (minimal 6 jam, maksimal 7 hari per request)
    - Response: per-symbol {total, severity maksimum, cells[{hour, count}]}
      diurutkan dari symbol paling aktif.
    """
    try:
        window = max(6, min(hours, 168))
        rows = await app_database.db.get_alert_heatmap(hours=window)

        grouped: Dict[str, Dict[str, Any]] = {}
        max_count = 0
        for r in rows:
            sym = str(r.get("symbol") or "UNKNOWN")
            hour = r.get("hour")
            hour_iso = hour.isoformat() if hasattr(hour, "isoformat") else str(hour)
            cnt = int(r.get("count") or 0)
            sev = int(r.get("severity") or 0)
            max_count = max(max_count, cnt)
            entry = grouped.setdefault(
                sym, {"symbol": sym, "total": 0, "severity": 0, "cells": []}
            )
            entry["cells"].append({"hour": hour_iso, "count": cnt})
            entry["total"] += cnt
            entry["severity"] = max(entry["severity"], sev)

        data = sorted(grouped.values(), key=lambda e: (-e["total"], e["symbol"]))
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "hours": window,
            "max_count": max_count,
            "count": len(data),
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/heatmap.csv", dependencies=API_DEPS)
async def export_alert_heatmap_csv(hours: int = 24):
    """Export agregasi heat map sebagai file CSV (v2.6).

    Kolom: symbol, hour (ISO-8601 UTC), alert_count, severity
    (0=low, 1=medium, 2=high). Window di-clamp 6..168 sama seperti
    endpoint JSON.
    """
    try:
        window = max(6, min(hours, 168))
        rows = await app_database.db.get_alert_heatmap(hours=window)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["symbol", "hour", "alert_count", "severity"])
        for r in rows:
            hour = r.get("hour")
            writer.writerow([
                r.get("symbol", ""),
                hour.isoformat() if hasattr(hour, "isoformat") else str(hour),
                int(r.get("count") or 0),
                int(r.get("severity") or 0),
            ])
        buffer.seek(0)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"alert_heatmap_{window}h_{stamp}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/alerts/retention", dependencies=API_DEPS)
async def get_alert_retention():
    """Info retensi alert_history untuk panel maintenance (v2.5).

    Menampilkan konfigurasi retensi, hasil prune terakhir, dan statistik
    tabel (total baris + baris tertua). Degradasi gracefully: bila DB
    gagal, konfigurasi tetap dikirim dengan flag db_ok=false.
    """
    settings = get_settings()
    retention_days = _effective_retention_days()
    interval = settings.alert_retention_interval_minutes

    db_ok = True
    total_alerts = None
    oldest_alert = None
    try:
        stats = await app_database.db.get_alert_history_stats()
        total_alerts = stats.get("total_alerts")
        oldest = stats.get("oldest_alert")
        oldest_alert = oldest.isoformat() if hasattr(oldest, "isoformat") else oldest
    except Exception as db_err:
        logger.warning(f"Alert retention stats unavailable: {db_err}")
        db_ok = False

    return {
        "status": "success",
        "timestamp": _utc_now_iso(),
        "data": {
            "retention_days": retention_days,
            "prune_interval_minutes": interval,
            "auto_prune_enabled": retention_days > 0,
            "last_prune": _last_prune,
            "total_alerts": total_alerts,
            "oldest_alert": oldest_alert,
            "db_ok": db_ok,
        },
    }


@router.post("/api/alerts/prune", dependencies=API_DEPS)
async def prune_alert_history(body: Optional[PruneRequest] = None):
    """Prune manual alert_history lebih tua dari N hari (v2.5).

    - Tanpa body: pakai settings.alert_history_retention_days
      (fallback 7 hari bila auto-prune dimatikan).
    - Body {days}: clamp 1..365 via pydantic.
    """
    try:
        settings = get_settings()
        days = body.days if (body and body.days) else _effective_retention_days()
        if not days or days <= 0:
            days = 7
        days = max(1, min(int(days), 365))

        deleted = await app_database.db.prune_alert_history(days)
        record_prune_result(_utc_now_iso(), deleted)
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "deleted": deleted,
            "retention_days_used": days,
            "data": {"last_prune": _last_prune},
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/telegram/status", dependencies=API_DEPS)
async def telegram_status():
    """Status konfigurasi notifikasi Telegram (v2.5, aman untuk publik).

    Token TIDAK PERNAH dikirim ke client - hanya flag configured,
    username bot, dan chat id yang disamarkan.
    """
    notifier = get_notifier()
    if notifier is not None and hasattr(notifier, "get_status"):
        data = notifier.get_status()
    else:
        data = {"configured": False, "bot_username": None, "chat_id_masked": None}
    data["db_connected"] = bool(getattr(app_database.db, "_initialized", False))
    return {
        "status": "success",
        "timestamp": _utc_now_iso(),
        "data": data,
    }


@router.post("/api/telegram/test", dependencies=API_DEPS)
async def send_telegram_test():
    """Kirim pesan test ke Telegram untuk verifikasi konfigurasi (v2.5).

    Pengiriman gagal dianggap HASIL (bukan error endpoint):
    response tetap status=success dengan flag sent=false + reason.
    """
    notifier = get_notifier()
    if notifier is None:
        return {
            "status": "success",
            "sent": False,
            "reason": "not_running",
            "message": "Telegram notifier is not running in this process.",
        }

    configured = False
    if hasattr(notifier, "get_status"):
        configured = bool(notifier.get_status().get("configured"))
    else:
        configured = bool(
            getattr(notifier, "bot", None) and getattr(notifier, "chat_id", None)
        )
    if not configured:
        return {
            "status": "success",
            "sent": False,
            "reason": "not_configured",
            "message": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable notifications.",
        }

    try:
        ok = await notifier.send_test_message()
        return {
            "status": "success",
            "sent": bool(ok),
            "reason": None if ok else "send_failed",
            "message": (
                "Test message delivered - check your Telegram chat."
                if ok else
                "Telegram rejected the message - check bot token / chat id."
            ),
        }
    except Exception as e:
        logger.warning(f"Telegram test send failed: {e}")
        return {"status": "success", "sent": False, "reason": "error", "message": str(e)}


# ===== v2.6: Runtime settings (GET/PUT) =====

async def _apply_telegram_update(key: str, value: str) -> Optional[Dict[str, Any]]:
    """Terapkan perubahan telegram_* ke notifier yang sedang berjalan.

    Telegram chat id hanya disimpan + diterapkan bersama token (chat id
    tanpa token tidak mengubah Bot). Return dict hasil reconfigure bila
    token baru diterapkan, selain itu None.
    """
    if key != "telegram_bot_token":
        return None
    notifier = get_notifier()
    if notifier is None or not hasattr(notifier, "reconfigure"):
        return {"ok": False, "reason": "not_running", "message": "Notifier not running"}
    chat_plain = None
    try:
        stored = await app_database.db.get_app_settings(keys=["telegram_chat_id"])
        raw = stored.get("telegram_chat_id")
        chat_plain = decrypt_secret(raw) if (raw and is_encrypted(raw)) else raw
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read stored chat_id for reconfigure: {e}")
    if not chat_plain:
        return {
            "ok": False,
            "reason": "missing_chat_id",
            "message": "Set telegram_chat_id together with the token.",
        }
    return await notifier.reconfigure(token=value, chat_id=chat_plain)


@router.get("/api/settings", dependencies=API_DEPS)
async def get_runtime_settings():
    """Daftar runtime settings yang bisa diubah dari dashboard (v2.6).

    Secret (telegram token/chat id) TIDAK pernah dikembalikan nilainya -
    hanya flag set/persisted dan chat id tersamarkan.
    """
    try:
        defaults = defaults_from_env()
        try:
            db_values = await load_overrides(app_database.db)
        except Exception as db_err:
            logger.warning(f"Runtime settings load failed: {db_err}")
            db_values = {}
        payload = build_settings_payload(db_values, defaults)
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "data": payload,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.put("/api/settings", dependencies=API_DEPS)
async def update_runtime_settings(body: SettingsUpdateRequest):
    """Terapkan + persist runtime settings (v2.6).

    - Key tidak dikenal -> entri results dgn ok=false, request tetap 200
      agar UI bisa menampilkan hasil per-key.
    - Nilai int di-clamp sesuai spec (warning dicatat).
    - telegram_bot_token diterapkan ke notifier runtime; bila gagal
      (token tidak valid / chat id belum ada), persist TETAP dilakukan
      hanya bila token diterima Telegram (hasil ok) agar DB tidak berisi
      token mati. chat_id selalu bisa dipersist sendiri.
    """
    results: Dict[str, Any] = {}
    notifier_state: Optional[Dict[str, Any]] = None

    for key, raw_value in body.updates.items():
        spec = SPECS_BY_KEY.get(key)
        if spec is None:
            results[key] = {"ok": False, "warning": "unknown key"}
            continue

        check = validate_value(spec, raw_value)
        if not check["ok"]:
            results[key] = {"ok": False, "warning": check["warning"]}
            continue

        value = check["value"]
        try:
            if spec["type"] == "secret" and key == "telegram_bot_token":
                stored_value = encrypt_secret(value)
            else:
                stored_value = value

            if key == "telegram_bot_token":
                # Terapkan dulu ke runtime; persist hanya bila token valid
                notifier_state = await _apply_telegram_update(key, value)
                if notifier_state and notifier_state.get("ok"):
                    await app_database.db.set_app_setting(key, stored_value)
                results[key] = {
                    "ok": bool(notifier_state and notifier_state.get("ok")),
                    "applied": bool(notifier_state and notifier_state.get("ok")),
                    "persisted": bool(notifier_state and notifier_state.get("ok")),
                    "warning": check["warning"],
                    "detail": notifier_state,
                }
                continue

            await app_database.db.set_app_setting(key, stored_value)
            # Perbarui cache override agar loop terpengaruh tanpa reload
            from app import runtime_settings as _rs
            _rs._cache[key] = stored_value
            results[key] = {
                "ok": True,
                "applied": True,
                "persisted": True,
                "warning": check["warning"],
            }
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to persist setting {key}: {e}")
            results[key] = {"ok": False, "warning": str(e)}

    return {
        "status": "success",
        "timestamp": _utc_now_iso(),
        "results": results,
    }


@router.get("/manifest.webmanifest", include_in_schema=False)
async def pwa_manifest():
    """PWA manifest (v2.6): membuat dashboard bisa di-install ke homescreen.

    Endpoint publik (tanpa auth) karena browser memuatnya di luar API
    context dan tidak membocorkan data apa pun.
    """
    from fastapi.responses import JSONResponse

    manifest = {
        "name": "Crypto Oracle AI",
        "short_name": "CryptoOracle",
        "description": "Real-time pump/dump detection dashboard",
        "start_url": "/dashboard",
        "scope": "/dashboard",
        "display": "standalone",
        "background_color": "#0a0e17",
        "theme_color": "#0a0e17",
        "icons": [
            {
                "src": "/static/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/static/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    return JSONResponse(content=manifest)


@router.post("/api/backtest/{symbol}", dependencies=API_DEPS)
async def run_symbol_backtest(symbol: str, body: BacktestRequest):
    """Jalankan backtest strategi volume-spike untuk satu symbol.

    - days di-clamp 1..90 (via pydantic)
    - volume_threshold di-clamp 10..10000 (via pydantic)
    """
    try:
        symbol = symbol.upper().strip()
        engine = get_backtest_engine()
        result = await engine.run_backtest(
            symbol=symbol,
            days=body.days,
            volume_threshold=body.volume_threshold,
        )
        if result.get("error"):
            return {"status": "error", "message": result["error"]}
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "data": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/sparkline/{symbol}", dependencies=API_DEPS)
async def get_sparkline(symbol: str, points: int = 60):
    """Riwayat harga kronologis untuk satu symbol (untuk grafik sparkline).

    - symbol dinormalisasi ke uppercase (konsisten dengan Binance pair)
    - points di-clamp 10..200 agar query tetap ringan
    """
    try:
        points = max(10, min(points, 200))
        symbol = symbol.upper().strip()
        history = await app_database.db.get_price_history(symbol, limit=points)
        return {
            "status": "success",
            "timestamp": _utc_now_iso(),
            "symbol": symbol,
            "count": len(history),
            "data": history,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/signals/validate/{symbol}")
async def validate_signal(symbol: str):
    """Validasi sinyal untuk symbol tertentu dengan multi-layer validation"""
    try:
        # Data simulasi untuk demonstrasi (akan diganti dengan data real dari streamer)
        mock_signal_data = {
            "symbol": symbol,
            "volume_change_percent": 450.5,
            "price_change_percent": 12.3,
            "smart_money_detected": True,
            "smart_wallet_count": 3,
            "sentiment_score": 0.75,
            "news_count": 5,
            "liquidity_locked": True,
            "liquidity_amount": 125000,
            "is_honeypot": False,
            "buy_tax": 5,
            "sell_tax": 8
        }

        validation_result = await signal_validator.validate_signal(mock_signal_data)

        return {
            "status": "success",
            "validation": validation_result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def _safe_remove_connection(websocket: WebSocket) -> None:
    """Hapus koneksi WebSocket dari daftar aktif dengan aman"""
    if websocket in active_connections:
        active_connections.remove(websocket)


@router.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket):
    """WebSocket endpoint untuk real-time updates"""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        # Kirim initial data
        await websocket.send_json({
            "type": "connection_established",
            "timestamp": _utc_now_iso(),
            "message": "Connected to Crypto Oracle AI dashboard"
        })

        # Keep connection alive
        while True:
            # Wait for messages (client can send commands)
            data = await websocket.receive_text()

            # Process client commands
            try:
                command = json.loads(data)
                if command.get("action") == "refresh":
                    # Send updated stats
                    stats = await get_dashboard_stats()
                    await websocket.send_json({
                        "type": "stats_update",
                        "data": stats
                    })
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        _safe_remove_connection(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        _safe_remove_connection(websocket)
