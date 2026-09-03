"""
Real-time Dashboard UI Module
- FastAPI routes untuk dashboard
- WebSocket untuk real-time updates
- HTML/CSS/JS frontend
"""
import json
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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


@router.get("/api/stats")
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


@router.get("/api/security/audit")
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
