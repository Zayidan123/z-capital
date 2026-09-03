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
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import database as app_database
from app.config import get_settings
from app.database import get_recent_signals, get_system_stats
from app.security.hardening import signal_validator, penetration_tester, dependency_auditor

router = APIRouter()

# Waktu proses dimulai - dipakai untuk metrik uptime di dashboard
_SERVICE_START_TIME = time.monotonic()

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


@router.get("/api/stats", dependencies=[Depends(require_api_key)])
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


@router.get("/api/security/audit", dependencies=[Depends(require_api_key)])
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


@router.get("/api/anomalies", dependencies=[Depends(require_api_key)])
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


@router.get("/api/export/signals.csv", dependencies=[Depends(require_api_key)])
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


@router.get("/api/symbols", dependencies=[Depends(require_api_key)])
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


@router.get("/api/sparkline/{symbol}", dependencies=[Depends(require_api_key)])
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
