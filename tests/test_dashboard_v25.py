"""
Tests untuk fitur Dashboard v2.5:
- Retensi alert_history: DB prune, endpoint retention/manual prune,
  loop housekeeping background di main.py
- Agregasi alert per-symbol per-jam (heat map): DB query + endpoint
- Panel notifikasi Telegram: status aman (tanpa token) + test-send
"""
import asyncio
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app.config import settings as app_settings
from app.notifier import TelegramNotifier
from app.ui import routes as ui_routes
from app.ui.rate_limit import reset_all_limiters


def _utc(hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 9, 3, hour, minute, tzinfo=timezone.utc)


def _make_db_with_conn(conn: MagicMock) -> app_database.Database:
    """Database dengan pool mock yang mengembalikan conn dari acquire()."""
    db = app_database.Database()
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    db.pool = pool
    db._initialized = True
    return db


@pytest.fixture
def v25_client():
    """TestClient + mock DB global untuk endpoint v2.5."""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = MagicMock()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

        # v2.5 methods pada global db (dipakai routes langsung)
        mock_global_db.get_alert_heatmap = AsyncMock(return_value=[])
        mock_global_db.get_alert_history_stats = AsyncMock(
            return_value={"total_alerts": 0, "oldest_alert": None}
        )
        mock_global_db.prune_alert_history = AsyncMock(return_value=0)
        mock_global_db._initialized = True
        # method lama yang dipakai endpoint lain saat lifespan start
        mock_global_db.get_recent_signals = AsyncMock(return_value=[])
        mock_global_db.get_recent_anomalies = AsyncMock(return_value=[])
        mock_global_db.get_system_stats = AsyncMock(return_value={
            "total_signals": 0, "signals_24h": 0, "total_anomalies": 0,
            "smart_wallets_count": 0, "success_rate": 0.0, "uptime_hours": 0,
        })
        mock_global_db.get_symbol_summary = AsyncMock(return_value=[])
        mock_global_db.get_price_history = AsyncMock(return_value=[])
        mock_global_db.get_alert_rule_thresholds = AsyncMock(return_value={})
        mock_global_db.get_alert_history = AsyncMock(return_value=[])

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        reset_all_limiters()
        ui_routes.reset_engines()

        from app.main import app
        with TestClient(app) as test_client:
            # lifespan memasang mock notifier (dari patch app.main) ->
            # reset agar test endpoint telegram mulai dari state tanpa notifier
            ui_routes.set_notifier(None)
            # Simpan referensi mock db untuk assert
            test_client._v25_mock_db = mock_global_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()


# ====================================================================
# 1. Config: field retensi baru
# ====================================================================

class TestConfigV25:
    def test_retention_defaults(self):
        assert app_settings.alert_history_retention_days == 7
        assert app_settings.alert_retention_interval_minutes == 60


# ====================================================================
# 2. Database layer: prune, heatmap, stats
# ====================================================================

class TestDatabaseV25:
    @pytest.mark.asyncio
    async def test_prune_returns_deleted_count(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 12")
        db = _make_db_with_conn(conn)

        deleted = await db.prune_alert_history(7)
        assert deleted == 12
        sql, *params = conn.execute.await_args.args
        assert "DELETE FROM alert_history" in sql
        assert "make_interval(days => $1)" in sql
        assert params[0] == 7

    @pytest.mark.asyncio
    async def test_prune_disabled_returns_zero_without_query(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _make_db_with_conn(conn)

        assert await db.prune_alert_history(0) == 0
        assert await db.prune_alert_history(-5) == 0
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prune_unexpected_status_returns_zero(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="WEIRD 1")
        db = _make_db_with_conn(conn)
        assert await db.prune_alert_history(7) == 0

    @pytest.mark.asyncio
    async def test_heatmap_sql_groups_by_symbol_and_hour(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        rows = await db.get_alert_heatmap(hours=24)
        assert rows == []
        sql, *params = conn.fetch.await_args.args
        assert "date_trunc('hour', timestamp)" in sql
        assert "make_interval(hours => $1)" in sql
        assert "GROUP BY symbol" in sql
        assert params[0] == 24

    @pytest.mark.asyncio
    async def test_heatmap_window_clamped(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_heatmap(hours=5000)
        assert conn.fetch.await_args.args[1] == 720  # clamp atas 30 hari
        await db.get_alert_heatmap(hours=0)
        assert conn.fetch.await_args.args[1] == 1  # clamp bawah

    @pytest.mark.asyncio
    async def test_alert_history_stats(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "total_alerts": 42, "oldest_alert": _utc(1),
        })
        db = _make_db_with_conn(conn)

        stats = await db.get_alert_history_stats()
        assert stats["total_alerts"] == 42
        sql = conn.fetchrow.await_args.args[0]
        assert "COUNT(*)" in sql and "MIN(timestamp)" in sql


# ====================================================================
# 3. Notifier: status aman tanpa token
# ====================================================================

class TestNotifierStatus:
    def _notifier(self) -> TelegramNotifier:
        return TelegramNotifier(MagicMock())

    def test_status_unconfigured(self):
        n = self._notifier()
        status = n.get_status()
        assert status["configured"] is False
        assert status["bot_username"] is None
        assert status["chat_id_masked"] is None
        # Token tidak pernah ada di output
        assert "token" not in {k.lower() for k in status}

    def test_status_masks_chat_id(self):
        n = self._notifier()
        n.chat_id = "123456789"
        status = n.get_status()
        assert status["chat_id_masked"] == "••••6789"
        assert "123456789" not in str(status)
        # Bot belum start -> configured tetap False
        assert status["configured"] is False

    def test_status_short_chat_id_fully_masked(self):
        n = self._notifier()
        n.chat_id = "42"
        assert n.get_status()["chat_id_masked"] == "••••"

    def test_status_configured_with_bot(self):
        n = self._notifier()
        n.chat_id = "987654321"
        n.bot = MagicMock()  # bot hadir -> configured
        n.bot_username = "oracle_bot"
        status = n.get_status()
        assert status["configured"] is True
        assert status["bot_username"] == "oracle_bot"


# ====================================================================
# 4. Routes: heatmap, retention, prune, telegram
# ====================================================================

class TestHeatmapEndpoint:
    def test_groups_and_sorts_symbols(self, v25_client):
        db = v25_client._v25_mock_db
        db.get_alert_heatmap = AsyncMock(return_value=[
            {"symbol": "PEPEUSDT", "hour": _utc(10), "count": 3, "severity": 2},
            {"symbol": "PEPEUSDT", "hour": _utc(11), "count": 1, "severity": 1},
            {"symbol": "DOGEUSDT", "hour": _utc(10), "count": 2, "severity": 0},
        ])

        res = v25_client.get("/dashboard/api/alerts/heatmap?hours=24")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["hours"] == 24
        assert body["max_count"] == 3
        assert body["count"] == 2
        # PEPEUSDT (total 4) di atas DOGEUSDT (total 2)
        top = body["data"][0]
        assert top["symbol"] == "PEPEUSDT"
        assert top["total"] == 4
        assert top["severity"] == 2
        assert len(top["cells"]) == 2
        assert body["data"][1]["symbol"] == "DOGEUSDT"
        assert body["data"][1]["total"] == 2

    def test_hours_clamped(self, v25_client):
        db = v25_client._v25_mock_db
        db.get_alert_heatmap = AsyncMock(return_value=[])

        v25_client.get("/dashboard/api/alerts/heatmap?hours=2")
        assert db.get_alert_heatmap.await_args.kwargs["hours"] == 6
        v25_client.get("/dashboard/api/alerts/heatmap?hours=9999")
        assert db.get_alert_heatmap.await_args.kwargs["hours"] == 168

    def test_db_error_returns_structured_error(self, v25_client):
        db = v25_client._v25_mock_db
        db.get_alert_heatmap = AsyncMock(side_effect=RuntimeError("db down"))

        res = v25_client.get("/dashboard/api/alerts/heatmap")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "error"
        assert "db down" in body["message"]


class TestRetentionEndpoints:
    def test_retention_info_default(self, v25_client):
        db = v25_client._v25_mock_db
        db.get_alert_history_stats = AsyncMock(
            return_value={"total_alerts": 42, "oldest_alert": _utc(1)}
        )

        res = v25_client.get("/dashboard/api/alerts/retention")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["retention_days"] == app_settings.alert_history_retention_days
        assert data["prune_interval_minutes"] == app_settings.alert_retention_interval_minutes
        assert data["auto_prune_enabled"] is True
        assert data["total_alerts"] == 42
        assert data["oldest_alert"].endswith("+00:00")
        assert data["db_ok"] is True
        assert data["last_prune"] is None

    def test_retention_info_db_failure_degrades(self, v25_client):
        db = v25_client._v25_mock_db
        db.get_alert_history_stats = AsyncMock(side_effect=RuntimeError("down"))

        res = v25_client.get("/dashboard/api/alerts/retention")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["db_ok"] is False
        assert data["total_alerts"] is None
        # Konfigurasi tetap dikirim meski DB mati
        assert data["retention_days"] == app_settings.alert_history_retention_days

    def test_manual_prune_uses_settings_default(self, v25_client):
        db = v25_client._v25_mock_db
        db.prune_alert_history = AsyncMock(return_value=5)

        res = v25_client.post("/dashboard/api/alerts/prune", json={})
        assert res.status_code == 200
        body = res.json()
        assert body["deleted"] == 5
        assert body["retention_days_used"] == app_settings.alert_history_retention_days
        db.prune_alert_history.assert_awaited_once_with(
            app_settings.alert_history_retention_days
        )
        # last_prune tercatat di state module
        assert ui_routes._last_prune is not None
        assert ui_routes._last_prune["rows"] == 5

    def test_manual_prune_with_body_days(self, v25_client):
        db = v25_client._v25_mock_db
        db.prune_alert_history = AsyncMock(return_value=9)

        res = v25_client.post("/dashboard/api/alerts/prune", json={"days": 30})
        assert res.status_code == 200
        assert res.json()["retention_days_used"] == 30
        db.prune_alert_history.assert_awaited_once_with(30)

    def test_manual_prune_fallback_when_auto_disabled(self, v25_client):
        db = v25_client._v25_mock_db
        db.prune_alert_history = AsyncMock(return_value=2)

        with patch("app.ui.routes.get_settings", return_value=SimpleNamespace(
                dashboard_api_key=None,
                alert_history_retention_days=0,
                alert_retention_interval_minutes=60)):
            res = v25_client.post("/dashboard/api/alerts/prune", json={})

        assert res.status_code == 200
        assert res.json()["retention_days_used"] == 7  # fallback manual

    def test_manual_prune_validates_days(self, v25_client):
        res = v25_client.post("/dashboard/api/alerts/prune", json={"days": 0})
        assert res.status_code == 422
        res = v25_client.post("/dashboard/api/alerts/prune", json={"days": 10000})
        assert res.status_code == 422


class TestTelegramEndpoints:
    def test_status_without_notifier(self, v25_client):
        res = v25_client.get("/dashboard/api/telegram/status")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["configured"] is False
        assert data["bot_username"] is None
        assert data["chat_id_masked"] is None
        # DB mock ter-initialize -> flag ikut status koneksi aktual
        assert data["db_connected"] is True

    def test_status_with_notifier_uses_get_status(self, v25_client):
        mock_notifier = MagicMock()
        mock_notifier.get_status.return_value = {
            "configured": True,
            "bot_username": "oracle_bot",
            "chat_id_masked": "••••6789",
        }
        ui_routes.set_notifier(mock_notifier)

        res = v25_client.get("/dashboard/api/telegram/status")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["configured"] is True
        assert data["bot_username"] == "oracle_bot"
        assert data["chat_id_masked"] == "••••6789"

    def test_test_send_without_notifier(self, v25_client):
        res = v25_client.post("/dashboard/api/telegram/test")
        assert res.status_code == 200
        body = res.json()
        assert body["sent"] is False
        assert body["reason"] == "not_running"

    def test_test_send_not_configured(self, v25_client):
        mock_notifier = MagicMock()
        mock_notifier.get_status.return_value = {"configured": False}
        ui_routes.set_notifier(mock_notifier)

        res = v25_client.post("/dashboard/api/telegram/test")
        body = res.json()
        assert body["sent"] is False
        assert body["reason"] == "not_configured"

    def test_test_send_success(self, v25_client):
        mock_notifier = MagicMock()
        mock_notifier.get_status.return_value = {"configured": True}
        mock_notifier.send_test_message = AsyncMock(return_value=True)
        ui_routes.set_notifier(mock_notifier)

        res = v25_client.post("/dashboard/api/telegram/test")
        body = res.json()
        assert body["sent"] is True
        assert body["reason"] is None
        mock_notifier.send_test_message.assert_awaited_once()

    def test_test_send_send_failed_is_result_not_error(self, v25_client):
        mock_notifier = MagicMock()
        mock_notifier.get_status.return_value = {"configured": True}
        mock_notifier.send_test_message = AsyncMock(return_value=False)
        ui_routes.set_notifier(mock_notifier)

        res = v25_client.post("/dashboard/api/telegram/test")
        body = res.json()
        assert body["sent"] is False
        assert body["reason"] == "send_failed"

    def test_test_send_exception_handled(self, v25_client):
        mock_notifier = MagicMock()
        mock_notifier.get_status.return_value = {"configured": True}
        mock_notifier.send_test_message = AsyncMock(
            side_effect=RuntimeError("network unreachable")
        )
        ui_routes.set_notifier(mock_notifier)

        res = v25_client.post("/dashboard/api/telegram/test")
        body = res.json()
        assert body["sent"] is False
        assert body["reason"] == "error"
        assert "network unreachable" in body["message"]


# ====================================================================
# 5. Main: loop retensi background
# ====================================================================

class TestRetentionLoop:
    def _make_app(self):
        from app.main import CryptoOracleApp
        return CryptoOracleApp()

    @pytest.mark.asyncio
    async def test_prune_once_disabled(self):
        app_inst = self._make_app()
        app_inst.settings = SimpleNamespace(alert_history_retention_days=0)
        app_inst.db = MagicMock()
        app_inst.db.prune_alert_history = AsyncMock()

        result = await app_inst._prune_alert_history_once()
        assert result is None
        app_inst.db.prune_alert_history.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prune_once_records_result(self):
        app_inst = self._make_app()
        app_inst.settings = SimpleNamespace(alert_history_retention_days=7)
        app_inst.db = MagicMock()
        app_inst.db.prune_alert_history = AsyncMock(return_value=12)

        result = await app_inst._prune_alert_history_once()
        assert result == 12
        app_inst.db.prune_alert_history.assert_awaited_once_with(7)
        # hasil tercatat untuk panel retention
        assert ui_routes._last_prune is not None
        assert ui_routes._last_prune["rows"] == 12
        ui_routes._last_prune = None

    @pytest.mark.asyncio
    async def test_retention_loop_survives_prune_error(self):
        app_inst = self._make_app()
        app_inst.settings = SimpleNamespace(alert_history_retention_days=3)
        app_inst.db = MagicMock()
        app_inst.db.prune_alert_history = AsyncMock(
            side_effect=RuntimeError("db down")
        )

        # sleep[0] -> prune error tertangkap; sleep[1] -> CancelledError keluar
        with patch("app.main.asyncio.sleep",
                   side_effect=[None, asyncio.CancelledError()]):
            await app_inst._alert_retention_loop(1)

        app_inst.db.prune_alert_history.assert_awaited_once_with(3)

    @pytest.mark.asyncio
    async def test_retention_loop_runs_periodically(self):
        app_inst = self._make_app()
        app_inst.settings = SimpleNamespace(alert_history_retention_days=5)
        app_inst.db = MagicMock()
        app_inst.db.prune_alert_history = AsyncMock(return_value=1)

        # 2 siklus lalu cancel
        with patch("app.main.asyncio.sleep",
                   side_effect=[None, None, asyncio.CancelledError()]):
            await app_inst._alert_retention_loop(1)

        assert app_inst.db.prune_alert_history.await_count == 2
