"""
Tests for the FastAPI endpoints (health, root, dashboard)
Lifespan dipatch dengan mock DB & stub streamer agar test tidak butuh
Postgres/akses internet.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient dengan lifespan yang aman (mock DB + stub streamer)"""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = MagicMock()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

        # Helper routes memakai instance global db dari app.database
        mock_global_db._initialized = True
        mock_global_db.get_recent_signals = AsyncMock(return_value=[
            {
                "id": 1,
                "symbol": "BTCUSDT",
                "signal_type": "PUMP_ALERT",
                "message": "SINYAL TEST",
                "status": "sent",
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ])
        mock_global_db.get_recent_anomalies = AsyncMock(return_value=[
            {
                "id": 1,
                "symbol": "BTCUSDT",
                "price": 50000.0,
                "volume_spike": 450.0,
                "volume_current": 1000.0,
                "volume_avg": 180.0,
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ])
        mock_global_db.get_system_stats = AsyncMock(return_value={
            "total_signals": 1,
            "signals_24h": 1,
            "total_anomalies": 5,
            "smart_wallets_count": 2,
            "success_rate": 100.0,
            "uptime_hours": 0,
        })

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        from app.main import app
        with TestClient(app) as test_client:
            yield test_client


class TestHealthEndpoint:
    """Test health check endpoint"""

    def test_health_check(self, client):
        """Test /health endpoint returns running status"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    def test_health_response_format(self, client):
        """Test health endpoint response format"""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "timestamp" in data


class TestRootEndpoint:
    """Test root endpoint"""

    def test_root_api_info(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Crypto Oracle AI"
        assert "endpoints" in data

    def test_openapi_docs_available(self, client):
        """Swagger UI tersedia di /docs"""
        response = client.get("/docs")
        assert response.status_code == 200


class TestDashboardRoutes:
    """Test dashboard routes"""

    def test_dashboard_home_renders(self, client):
        """Bug lama: template path hard-coded /app/ui/templates"""
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert "Crypto Oracle" in response.text

    def test_dashboard_stats_endpoint(self, client):
        """Bug lama: frontend fetch /api/stats padahal route ada di /dashboard/api/stats"""
        response = client.get("/dashboard/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "signals" in data["data"]
        assert "system" in data["data"]
        # Uptime harus angka real (>= 0), bukan selalu 0
        assert data["data"]["uptime"] >= 0

    def test_security_audit_endpoint_no_crash(self, client):
        """Bug lama: AttributeError settings.TELEGRAM_BOT_TOKEN saat audit"""
        response = client.get("/dashboard/api/security/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "audit" in data

    def test_validate_signal_endpoint(self, client):
        response = client.get("/dashboard/api/signals/validate/BTCUSDT")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["validation"]["symbol"] == "BTCUSDT"

    def test_anomalies_endpoint(self, client):
        """Endpoint baru: daftar anomali volume terbaru"""
        response = client.get("/dashboard/api/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["count"] == 1
        assert data["data"][0]["symbol"] == "BTCUSDT"
        assert data["data"][0]["volume_spike"] == 450.0

    def test_anomalies_endpoint_with_symbol_filter(self, client):
        response = client.get("/dashboard/api/anomalies", params={"symbol": "ETHUSDT", "limit": 10})
        assert response.status_code == 200
        # Verifikasi filter & limit diteruskan ke DB
        from app.database import db as global_db
        kwargs = global_db.get_recent_anomalies.call_args.kwargs
        assert kwargs.get("symbol") == "ETHUSDT"
        assert kwargs.get("limit") == 10

    def test_export_signals_csv(self, client):
        """Endpoint baru: export sinyal ke CSV"""
        response = client.get("/dashboard/api/export/signals.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        body = response.text
        lines = body.strip().splitlines()
        assert lines[0] == "id,symbol,signal_type,status,timestamp,message"
        assert "BTCUSDT" in lines[1]

    def test_stats_endpoint_contains_system_meta(self, client):
        """Stats harus menyertakan metrik sistem untuk meta cards"""
        response = client.get("/dashboard/api/stats")
        data = response.json()
        system = data["data"]["system"]
        assert "total_anomalies" in system
        assert "smart_wallets_count" in system
        assert "total_signals" in system
