"""
Tests untuk fitur Dashboard v2.3:
- Rate limiter per-IP (sliding window) untuk semua endpoint /api/*
- GET/PUT /dashboard/api/alerts/rules + GET /dashboard/api/alerts/history
- GET /dashboard/api/symbol/{symbol} (detail: summary + history + anomalies)
- POST /dashboard/api/backtest/{symbol} (BacktestEngine dengan harga riil)
- AlertSystem data-driven: threshold editable, requires, rate limit alert
"""
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ui import routes as ui_routes
from app.ui.rate_limit import RateLimiter, reset_all_limiters
from app.dashboard import AlertSystem, BacktestEngine


def _aware(hours_ago: float = 0.0) -> datetime:
    """Timestamp timezone-aware relatif terhadap sekarang."""
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


@pytest.fixture
def v23_client():
    """TestClient + mock DB global (menyediakan semua method v2.2/v2.3)."""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = MagicMock()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

        mock_global_db._initialized = True
        mock_global_db.get_recent_signals = AsyncMock(return_value=[])
        mock_global_db.get_recent_anomalies = AsyncMock(return_value=[])
        mock_global_db.get_system_stats = AsyncMock(return_value={
            "total_signals": 0, "signals_24h": 0, "total_anomalies": 0,
            "smart_wallets_count": 0, "success_rate": 0.0, "uptime_hours": 0,
        })
        mock_global_db.get_symbol_summary = AsyncMock(return_value=[
            {
                "symbol": "PEPEUSDT",
                "anomaly_count": 30,
                "avg_spike": 425.5,
                "last_price": 0.0000121,
                "last_seen": _aware(0.1).isoformat(),
            },
        ])
        mock_global_db.get_price_history = AsyncMock(return_value=[
            {"price": 0.0000110, "volume_spike": 800.0, "timestamp": _aware(1.0).isoformat()},
            {"price": 0.0000121, "volume_spike": 850.0, "timestamp": _aware(0.5).isoformat()},
        ])

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        # State bersih untuk rate limiter & engines
        reset_all_limiters()
        ui_routes.reset_engines()

        from app.main import app
        with TestClient(app) as test_client:
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()


# ============================================================
# Unit: RateLimiter
# ============================================================
class TestRateLimiterUnit:
    """Perilaku dasar sliding window."""

    def test_allows_up_to_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for i in range(3):
            allowed, retry = rl.check("ip1")
            assert allowed, f"request {i + 1} harus diizinkan"
            assert retry == 0.0

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        assert rl.check("ip1")[0] is True
        assert rl.check("ip1")[0] is True
        allowed, retry = rl.check("ip1")
        assert allowed is False
        assert retry >= 1.0  # retry_after dibulatkan ke atas minimal 1 detik

    def test_per_key_isolation(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        assert rl.check("ip1")[0] is True
        assert rl.check("ip1")[0] is False
        assert rl.check("ip2")[0] is True  # IP lain tidak terpengaruh

    def test_window_expiry(self):
        rl = RateLimiter(max_requests=1, window_seconds=0.05)
        assert rl.check("ip1")[0] is True
        assert rl.check("ip1")[0] is False
        import time
        time.sleep(0.07)
        assert rl.check("ip1")[0] is True  # window lewat -> boleh lagi

    def test_disabled_when_zero(self):
        rl = RateLimiter(max_requests=0, window_seconds=60)
        for _ in range(100):
            assert rl.check("ip1")[0] is True

    def test_reset(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.check("ip1")
        rl.reset()
        assert rl.check("ip1")[0] is True


# ============================================================
# Integration: rate limit 429 via HTTP
# ============================================================
class TestRateLimitHTTP:
    def test_429_after_limit_with_retry_after(self, v23_client):
        fake = SimpleNamespace(dashboard_rate_limit=3, dashboard_rate_limit_window=60)
        with patch("app.ui.rate_limit.get_settings", return_value=fake):
            reset_all_limiters()
            for _ in range(3):
                resp = v23_client.get("/dashboard/api/symbols")
                assert resp.status_code == 200
            resp = v23_client.get("/dashboard/api/symbols")
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert int(resp.headers["Retry-After"]) >= 1
            assert resp.json()["detail"]  # pesan error ada
        reset_all_limiters()

    def test_html_page_not_rate_limited(self, v23_client):
        """Halaman HTML dan WS tidak masuk rate limit (hanya /api/*)."""
        fake = SimpleNamespace(dashboard_rate_limit=1, dashboard_rate_limit_window=60)
        with patch("app.ui.rate_limit.get_settings", return_value=fake):
            reset_all_limiters()
            for _ in range(4):
                resp = v23_client.get("/dashboard/")
                assert resp.status_code == 200
        reset_all_limiters()


# ============================================================
# Alert rules endpoints
# ============================================================
class TestAlertRulesEndpoints:
    def test_get_rules_default(self, v23_client):
        resp = v23_client.get("/dashboard/api/alerts/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["count"] == 4
        names = {r["name"] for r in data["data"]}
        assert "extreme_volume_spike" in names
        assert "confirmed_signal" in names
        rule = next(r for r in data["data"] if r["name"] == "extreme_volume_spike")
        assert rule["editable"] is True
        assert rule["threshold"] == 500.0
        assert rule["threshold_key"] == "volume_spike"

    def test_put_rule_updates_threshold(self, v23_client):
        resp = v23_client.put(
            "/dashboard/api/alerts/rules/extreme_volume_spike",
            json={"threshold": 750.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["threshold"] == 750.0
        # Engine singleton benar-benar berubah
        engine = ui_routes.get_alert_system()
        assert engine.alert_rules[0]["threshold"] == 750.0

    def test_put_unknown_rule_404(self, v23_client):
        resp = v23_client.put(
            "/dashboard/api/alerts/rules/no_such_rule",
            json={"threshold": 1.0},
        )
        assert resp.status_code == 404

    def test_put_non_editable_rule_400(self, v23_client):
        resp = v23_client.put(
            "/dashboard/api/alerts/rules/smart_money_detected",
            json={"threshold": 1.0},
        )
        assert resp.status_code == 400

    def test_put_negative_threshold_422(self, v23_client):
        resp = v23_client.put(
            "/dashboard/api/alerts/rules/extreme_volume_spike",
            json={"threshold": -5},
        )
        assert resp.status_code == 422

    def test_alert_history_empty(self, v23_client):
        resp = v23_client.get("/dashboard/api/alerts/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["count"] == 0
        assert data["data"] == []


# ============================================================
# Symbol detail endpoint
# ============================================================
class TestSymbolDetailEndpoint:
    def test_detail_success(self, v23_client):
        resp = v23_client.get("/dashboard/api/symbol/PEPEUSDT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["symbol"] == "PEPEUSDT"
        assert data["data"]["summary"]["anomaly_count"] == 30
        assert len(data["data"]["history"]) == 2
        # History kronologis lama -> baru
        prices = [p["price"] for p in data["data"]["history"]]
        assert prices == sorted(prices)

    def test_detail_uppercase_normalization(self, v23_client):
        resp = v23_client.get("/dashboard/api/symbol/pepeusdt")
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "PEPEUSDT"

    def test_detail_unknown_symbol_404(self, v23_client):
        """404 hanya bila summary/anomali/history semuanya kosong."""
        from app.database import db as global_db
        global_db.get_recent_anomalies = AsyncMock(return_value=[])
        global_db.get_price_history = AsyncMock(return_value=[])
        resp = v23_client.get("/dashboard/api/symbol/UNKNOWNCOIN")
        assert resp.status_code == 404

    def test_detail_db_error_structured(self, v23_client):
        from app.database import db as global_db
        global_db.get_symbol_summary = AsyncMock(side_effect=RuntimeError("db down"))
        resp = v23_client.get("/dashboard/api/symbol/PEPEUSDT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "db down" in data["message"]


# ============================================================
# Backtest endpoint + engine
# ============================================================
class TestBacktestEndpoint:
    def _seed_backtest_data(self, mock_db):
        """Anomali 1 jam lalu (spike 500 @ 100) + history harga setelahnya."""
        t_entry = _aware(1.0)
        mock_db.get_recent_anomalies = AsyncMock(return_value=[
            {"symbol": "PEPEUSDT", "price": 100.0, "volume_spike": 500.0,
             "timestamp": t_entry},
            {"symbol": "PEPEUSDT", "price": 50.0, "volume_spike": 250.0,
             "timestamp": t_entry},  # di bawah threshold 300 -> bukan trade
        ])
        mock_db.get_price_history = AsyncMock(return_value=[
            {"price": 98.0, "volume_spike": 100.0,
             "timestamp": (t_entry - timedelta(minutes=10)).isoformat()},
            {"price": 105.0, "volume_spike": 100.0,
             "timestamp": (t_entry + timedelta(minutes=20)).isoformat()},
            {"price": 110.0, "volume_spike": 100.0,
             "timestamp": (t_entry + timedelta(minutes=40)).isoformat()},
        ])

    def test_backtest_success_real_prices(self, v23_client):
        from app.database import db as global_db
        self._seed_backtest_data(global_db)

        resp = v23_client.post(
            "/dashboard/api/backtest/PEPEUSDT",
            json={"days": 7, "volume_threshold": 300},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        result = data["data"]

        # Hanya anomali spike >= 300 yang jadi trade; exit pakai harga riil
        assert result["total_signals"] == 1
        trade = result["hypothetical_trades"][0]
        assert trade["entry_price"] == 100.0
        assert trade["exit_price"] == 110.0  # titik terakhir dalam horizon
        assert trade["pnl_percent"] == pytest.approx(10.0)
        assert result["performance"]["win_rate"] == 1.0
        assert result["data_points"] == 3

    def test_backtest_uppercase(self, v23_client):
        from app.database import db as global_db
        self._seed_backtest_data(global_db)
        resp = v23_client.post(
            "/dashboard/api/backtest/pepeusdt", json={"days": 7}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_backtest_validation_error(self, v23_client):
        # days=0 di luar range 1..90 -> 422 oleh pydantic
        resp = v23_client.post(
            "/dashboard/api/backtest/PEPEUSDT", json={"days": 0}
        )
        assert resp.status_code == 422

    def test_backtest_db_error_structured(self, v23_client):
        from app.database import db as global_db
        global_db.get_recent_anomalies = AsyncMock(side_effect=RuntimeError("boom"))
        resp = v23_client.post(
            "/dashboard/api/backtest/PEPEUSDT", json={"days": 7}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"


class TestBacktestEngineUnit:
    """Perilaku engine langsung: horizon exit, skip price <= 0."""

    def _make_engine(self):
        db = MagicMock()
        db.get_recent_anomalies = AsyncMock()
        db.get_price_history = AsyncMock()
        return BacktestEngine(db)

    def test_skip_zero_price_no_crash(self):
        """BUG LAMA: entry_price 0 -> ZeroDivisionError. Sekarang di-skip."""
        engine = self._make_engine()
        t = _aware(0.2)
        engine.db.get_recent_anomalies = AsyncMock(return_value=[
            {"price": 0, "volume_spike": 900.0, "timestamp": t},
            {"price": None, "volume_spike": 900.0, "timestamp": t},
        ])
        engine.db.get_price_history = AsyncMock(return_value=[
            {"price": 1.0, "timestamp": (t + timedelta(minutes=10)).isoformat()},
        ])
        import asyncio
        result = asyncio.run(
            engine.run_backtest("X", days=7, volume_threshold=300)
        )
        assert result["total_signals"] == 0
        assert "error" not in result

    def test_no_future_price_skips_trade(self):
        """Tanpa titik harga setelah entry -> trade tidak dievaluasi."""
        engine = self._make_engine()
        t = _aware(0.2)
        engine.db.get_recent_anomalies = AsyncMock(return_value=[
            {"price": 100.0, "volume_spike": 500.0, "timestamp": t},
        ])
        engine.db.get_price_history = AsyncMock(return_value=[
            {"price": 99.0, "timestamp": (t - timedelta(minutes=5)).isoformat()},
        ])
        import asyncio
        result = asyncio.run(
            engine.run_backtest("X", days=7, volume_threshold=300)
        )
        assert result["total_signals"] == 0

    def test_exit_beyond_horizon_uses_first_available(self):
        engine = self._make_engine()
        t = _aware(1.0)
        engine.db.get_recent_anomalies = AsyncMock(return_value=[
            {"price": 100.0, "volume_spike": 500.0, "timestamp": t},
        ])
        engine.db.get_price_history = AsyncMock(return_value=[
            {"price": 120.0, "timestamp": (t + timedelta(minutes=15)).isoformat()},
            {"price": 80.0, "timestamp": (t + timedelta(minutes=75)).isoformat()},  # > 60m horizon
        ])
        import asyncio
        result = asyncio.run(
            engine.run_backtest("X", days=7, volume_threshold=300)
        )
        # Eksekusi exit = titik pertama setelah horizon 60 menit
        assert result["hypothetical_trades"][0]["exit_price"] == 80.0
        assert result["performance"]["win_rate"] == 0.0


# ============================================================
# AlertSystem data-driven
# ============================================================
class TestAlertSystemUnit:
    def _make_system(self) -> AlertSystem:
        system = AlertSystem(MagicMock())
        system._load_default_rules()
        return system

    async def test_threshold_rule_triggers(self):
        system = self._make_system()
        alerts = await system.check_alerts({"symbol": "X", "volume_spike": 600})
        assert len(alerts) == 1
        assert alerts[0]["rule"] == "extreme_volume_spike"

    async def test_below_threshold_no_trigger(self):
        system = self._make_system()
        alerts = await system.check_alerts({"symbol": "X", "volume_spike": 400})
        assert alerts == []

    async def test_set_threshold_changes_behavior(self):
        system = self._make_system()
        system.set_rule_threshold("extreme_volume_spike", 700)
        assert await system.check_alerts({"symbol": "X", "volume_spike": 600}) == []
        assert len(await system.check_alerts({"symbol": "X", "volume_spike": 800})) == 1

    async def test_confirmed_requires_confirmed_flag(self):
        """BUG LOGIKA: confidence tinggi tanpa confirmed=True tidak boleh trigger."""
        system = self._make_system()
        alerts = await system.check_alerts({"symbol": "X", "confidence_score": 0.9, "confirmed": False})
        assert alerts == []
        alerts = await system.check_alerts({"symbol": "X", "confidence_score": 0.9, "confirmed": True})
        assert any(a["rule"] == "confirmed_signal" for a in alerts)

    def test_non_editable_raises(self):
        system = self._make_system()
        with pytest.raises(ValueError):
            system.set_rule_threshold("smart_money_detected", 1.0)

    def test_unknown_rule_raises(self):
        system = self._make_system()
        with pytest.raises(KeyError):
            system.set_rule_threshold("does_not_exist", 1.0)

    async def test_alert_rate_limit_same_rule_symbol(self):
        system = self._make_system()
        payload = {"symbol": "X", "volume_spike": 900}
        assert len(await system.check_alerts(payload)) == 1
        # Trigger kedua < 5 menit untuk rule+symbol sama dibungkam
        assert await system.check_alerts(payload) == []

    def test_get_rules_serializable(self):
        system = self._make_system()
        rules = system.get_rules()
        for rule in rules:
            assert "condition" not in rule  # lambda tidak boleh bocor ke JSON
            assert "name" in rule and "priority" in rule

    async def test_invalid_threshold_value_safe(self):
        """Nilai non-numerik pada threshold rule -> tidak crash, hanya tidak match."""
        system = self._make_system()
        alerts = await system.check_alerts({"symbol": "X", "volume_spike": "abc"})
        assert alerts == []
