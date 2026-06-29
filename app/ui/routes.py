"""
Real-time Dashboard UI Module
- FastAPI routes untuk dashboard
- WebSocket untuk real-time updates
- HTML/CSS/JS frontend
"""
import json
import asyncio
from typing import Dict, List, Any
from datetime import datetime
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.database import get_recent_signals, get_system_stats
from app.security.hardening import signal_validator, penetration_tester, dependency_auditor

router = APIRouter()
templates = Jinja2Templates(directory="/app/ui/templates")

# Store connected WebSocket clients
active_connections: List[WebSocket] = []

async def broadcast_update(data: Dict[str, Any]):
    """Kirim update ke semua client WebSocket yang terhubung"""
    if not active_connections:
        return
    
    message = json.dumps(data)
    disconnected = []
    
    for connection in active_connections:
        try:
            await connection.send_text(message)
        except Exception:
            disconnected.append(connection)
    
    # Remove disconnected clients
    for conn in disconnected:
        active_connections.remove(conn)


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Halaman utama dashboard"""
    # Perbaikan bug: TemplateResponse memerlukan parameter 'name' dan 'context' secara eksplisit
    context = {
        "request": request,
        "title": "Crypto Oracle AI - Dashboard"
    }
    return templates.TemplateResponse(name="dashboard.html", context=context)


@router.get("/api/stats")
async def get_dashboard_stats():
    """API endpoint untuk statistik real-time"""
    try:
        # Ambil data dari database
        recent_signals = await get_recent_signals(limit=50)
        system_stats = await get_system_stats()
        
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "signals": recent_signals,
                "system": system_stats,
                "uptime": system_stats.get("uptime_hours", 0)
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


@router.websocket("/ws/updates")
async def websocket_updates(websocket: WebSocket):
    """WebSocket endpoint untuk real-time updates"""
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        # Kirim initial data
        await websocket.send_json({
            "type": "connection_established",
            "timestamp": datetime.utcnow().isoformat(),
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
        active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)
