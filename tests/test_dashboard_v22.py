"""
Tests untuk fitur Dashboard v2.2:
- GET /dashboard/api/symbols      (ringkasan per-symbol untuk Market Pulse)
- GET /dashboard/api/sparkline/{symbol} (riwayat harga kronologis)
- Opt-in API key auth (header X-API-Key) untuk endpoint /api/*
- Database.get_price_history / get_symbol_summary (dengan mock pool)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


@pytest.fixture
def v22_client():
    """TestClient + mock DB global dengan method baru v2.2 (symbols, sparkline)"""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = MagicMock()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

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
        mock_global_db.get_recent_anomalies = AsyncMock(return_value=[])
        mock_global_db.get_system_stats = AsyncMock(return_value={
            "total_signals": 1,
            "signals_24h": 1,
            "total_anomalies": 5,
            "smart_wallets_count": 2,
            "success_rate": 100.0,
            "uptime_hours": 0,
        })
        # Method baru v2.2
        mock_global_db.get_symbol_summary = AsyncMock(return_value=[
            {
                "symbol": "PEPEUSDT",
                "anomaly_count": 30,
                "avg_spike": 425.5,
                "last_price": 0.0000121,
                "last_seen": "2026-01-01T00:00:00+00:00",
            },
            {
                "symbol": "DOGEUSDT",
                "anomaly_count": 12,
                "avg_spike": 310.0,
                "last_price": 0.1623,
                "last_seen": "2026-01-01T00:00:00+00:00",
            },
        ])
        # Riwayat kronologis (lama -> baru)
        mock_global_db.get_price_history = AsyncMock(return_value=[
            {"price": 0.0000110, "volume_spike": 800.0, "timestamp": "2026-01-01T00:00:00+00:00"},
            {"price": 0.0000121, "volume_spike": 850.0, "timestamp": "2026-01-01T00:05:00+00:00"},
        ])

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        from app.main import app
        with TestClient(app) as test_client:
            yield test_client


class TestSymbolsEndpoint:
    """GET /dashboard/api/symbols untuk Market Pulse & filter dropdown"""

    def test_symbols_endpoint_success(self, v22_client):
        response = v22_client.get("/dashboard/api/symbols")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["count"] == 2
        assert data["data"][0]["symbol"] == "PEPEUSDT"
        assert data["data"][0]["anomaly_count"] == 30
        assert "timestamp" in data

    def test_symbols_endpoint_calls_summary(self, v22_client):
        v22_client.get("/dashboard/api/symbols")
        from app.database import db as global_db
        global_db.get_symbol_summary.assert_awaited_once()

    def test_symbols_endpoint_empty(self, v22_client):
        """DB kosong -> count 0 tapi tetap success (bukan error)"""
        from app.database import db as global_db
        global_db.get_symbol_summary = AsyncMock(return_value=[])
        response = v22_client.get("/dashboard/api/symbols")
        data = response.json()
        assert data["status"] == "success"
        assert data["count"] == 0
        assert data["data"] == []


class TestSparklineEndpoint:
    """GET /dashboard/api/sparkline/{symbol} untuk grafik harga"""

    def test_sparkline_success_chronological(self, v22_client):
        response = v22_client.get("/dashboard/api/sparkline/PEPEUSDT")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["symbol"] == "PEPEUSDT"
        assert data["count"] == 2
        # Data harus kronologis: harga pertama < harga kedua (lama -> baru)
        prices = [p["price"] for p in data["data"]]
        assert prices == sorted(prices)

    def test_sparkline_symbol_uppercased(self, v22_client):
        """Symbol lowercase harus dinormalisasi ke uppercase"""
        v22_client.get("/dashboard/api/sparkline/pepeusdt")
        from app.database import db as global_db
        args, kwargs = global_db.get_price_history.call_args
        assert args[0] == "PEPEUSDT"

    def test_sparkline_points_clamped_low(self, v22_client):
        """points di bawah minimum (10) di-clamp agar query tetap sehat"""
        v22_client.get("/dashboard/api/sparkline/PEPEUSDT", params={"points": 1})
        from app.database import db as global_db
        kwargs = global_db.get_price_history.call_args.kwargs
        assert kwargs.get("limit") == 10

    def test_sparkline_points_clamped_high(self, v22_client):
        """points di atas maksimum (200) di-clamp untuk cegah abuse"""
        v22_client.get("/dashboard/api/sparkline/PEPEUSDT", params={"points": 99999})
        from app.database import db as global_db
        kwargs = global_db.get_price_history.call_args.kwargs
        assert kwargs.get("limit") == 200

    def test_sparkline_db_error_returns_error_status(self, v22_client):
        """DB gagal -> status error terstruktur, bukan 500"""
        from app.database import db as global_db
        global_db.get_price_history = AsyncMock(side_effect=RuntimeError("db down"))
        response = v22_client.get("/dashboard/api/sparkline/PEPEUSDT")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "db down" in data["message"]


class TestApiKeyAuth:
    """Opt-in API key auth: aktif hanya jika settings.dashboard_api_key di-set"""

    def test_auth_disabled_by_default(self, v22_client):
        """Tanpa DASHBOARD_API_KEY -> semua endpoint terbuka (mode lokal)"""
        response = v22_client.get("/dashboard/api/stats")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def _enable_auth(self, api_key: str):
        """Patch get_settings di module routes agar auth aktif"""
        mock_settings = MagicMock()
        mock_settings.dashboard_api_key = api_key
        return patch("app.ui.routes.get_settings", return_value=mock_settings)

    def test_missing_key_returns_401(self, v22_client):
        with self._enable_auth("rahasia123"):
            response = v22_client.get("/dashboard/api/stats")
        assert response.status_code == 401
        assert "X-API-Key" in response.json()["detail"]

    def test_wrong_key_returns_401(self, v22_client):
        with self._enable_auth("rahasia123"):
            response = v22_client.get(
                "/dashboard/api/stats", headers={"X-API-Key": "salah"})
        assert response.status_code == 401

    def test_correct_key_returns_200(self, v22_client):
        with self._enable_auth("rahasia123"):
            response = v22_client.get(
                "/dashboard/api/stats", headers={"X-API-Key": "rahasia123"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_auth_covers_export_and_new_endpoints(self, v22_client):
        """Auth juga melindungi export CSV, anomalies, symbols, sparkline"""
        with self._enable_auth("k"):
            for path in (
                "/dashboard/api/export/signals.csv",
                "/dashboard/api/anomalies",
                "/dashboard/api/symbols",
                "/dashboard/api/sparkline/PEPEUSDT",
            ):
                response = v22_client.get(path)
                assert response.status_code == 401, f"{path} tidak terproteksi"

    def test_dashboard_page_not_protected(self, v22_client):
        """Halaman HTML tetap bisa dibuka tanpa key (WS browser tak bisa kirim header)"""
        with self._enable_auth("k"):
            response = v22_client.get("/dashboard/")
        assert response.status_code == 200
        assert "Crypto Oracle" in response.text


class TestDatabaseNewMethods:
    """Unit test method DB baru dengan mock pool"""

    @pytest.fixture
    def mock_db(self):
        from app.database import Database
        db = Database()
        db.pool = MagicMock()
        db._initialized = True
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {"price": 0.0000121, "volume_spike": 850.0, "timestamp": "2026-01-01T00:05:00+00:00"},
            {"price": 0.0000110, "volume_spike": 800.0, "timestamp": "2026-01-01T00:00:00+00:00"},
        ])
        db.pool.acquire = AsyncMock(return_value=conn)
        db.pool.release = AsyncMock()
        db._mock_conn = conn
        return db

    @pytest.mark.asyncio
    async def test_get_price_history_reversed(self, mock_db):
        """Hasil SQL DESC harus di-reverse menjadi kronologis (lama -> baru)"""
        history = await mock_db.get_price_history("PEPEUSDT", limit=40)
        prices = [h["price"] for h in history]
        assert prices[0] == 0.0000110  # data lama duluan
        assert prices[1] == 0.0000121
        args = mock_db._mock_conn.fetch.call_args[0]
        assert "WHERE symbol = $1" in args[0]
        assert "ORDER BY timestamp DESC" in args[0]

    @pytest.mark.asyncio
    async def test_get_symbol_summary_query(self, mock_db):
        """get_symbol_summary memakai aggregate GROUP BY symbol"""
        mock_db._mock_conn.fetch = AsyncMock(return_value=[
            {"symbol": "PEPEUSDT", "anomaly_count": 30, "avg_spike": 425.5,
             "last_price": 0.0000121, "last_seen": "2026-01-01T00:00:00+00:00"},
        ])
        summary = await mock_db.get_symbol_summary()
        assert len(summary) == 1
        assert summary[0]["anomaly_count"] == 30
        query = mock_db._mock_conn.fetch.call_args[0][0]
        assert "GROUP BY symbol" in query
        assert "ORDER BY anomaly_count DESC" in query
