"""
Tests untuk fitur Dashboard v2.4:
- Persistensi alert rules ke DB (tabel alert_rules) -> survive restart
- Persistensi alert history ke DB (tabel alert_history) + fallback in-memory
- Wire AlertSystem ke pipeline utama (_handle_anomaly) + callback broadcast WS
- Endpoint /api/alerts/history dengan sumber database/memory
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app.dashboard import AlertSystem
from app.ui import routes as ui_routes
from app.ui.rate_limit import reset_all_limiters


def _aware(hours_ago: float = 0.0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def _make_mock_db() -> MagicMock:
    """Mock Database dengan method v2.4."""
    mock = MagicMock()
    mock.get_alert_rule_thresholds = AsyncMock(return_value={})
    mock.upsert_alert_rule_threshold = AsyncMock()
    mock.log_alert = AsyncMock(return_value=1)
    mock.get_alert_history = AsyncMock(return_value=[])
    return mock


def _make_db_with_conn(conn: MagicMock) -> MagicMock:
    """Database dengan pool mock yang mengembalikan conn dari acquire()."""
    db = app_database.Database()
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    db.pool = pool
    db._initialized = True
    return db


@pytest.fixture
def v24_client():
    """TestClient + mock DB global untuk endpoint v2.4."""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = _make_mock_db()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

        # Global db dipakai routes & AlertSystem singleton
        for attr in ("get_alert_rule_thresholds", "upsert_alert_rule_threshold",
                     "log_alert", "get_alert_history"):
            setattr(mock_global_db, attr, getattr(mock_db, attr))
        mock_global_db._initialized = True
        mock_global_db.get_recent_signals = AsyncMock(return_value=[])
        mock_global_db.get_recent_anomalies = AsyncMock(return_value=[])
        mock_global_db.get_system_stats = AsyncMock(return_value={
            "total_signals": 0, "signals_24h": 0, "total_anomalies": 0,
            "smart_wallets_count": 0, "success_rate": 0.0, "uptime_hours": 0,
        })
        mock_global_db.get_symbol_summary = AsyncMock(return_value=[])
        mock_global_db.get_price_history = AsyncMock(return_value=[])

        # Component instances: start/stop harus async
        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        reset_all_limiters()
        ui_routes.reset_engines()

        from app.main import app
        with TestClient(app) as test_client:
            # Simpan referensi mock db untuk assert
            test_client._v24_mock_db = mock_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()


# ====================================================================
# 1. Database layer: alert_rules & alert_history
# ====================================================================

class TestDatabaseV24:
    @pytest.mark.asyncio
    async def test_get_alert_rule_thresholds_returns_dict(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {"name": "extreme_volume_spike", "threshold": 750.5},
            {"name": "confirmed_signal", "threshold": 0.8},
        ])
        db = _make_db_with_conn(conn)

        result = await db.get_alert_rule_thresholds()
        assert result == {"extreme_volume_spike": 750.5, "confirmed_signal": 0.8}

    @pytest.mark.asyncio
    async def test_upsert_alert_rule_threshold_executes(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _make_db_with_conn(conn)

        await db.upsert_alert_rule_threshold("extreme_volume_spike", 650.0)
        conn.execute.assert_awaited_once()
        sql = conn.execute.await_args.args[0]
        assert "INSERT INTO alert_rules" in sql
        assert "ON CONFLICT (name) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_log_alert_serializes_data_to_jsonb(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 42})
        db = _make_db_with_conn(conn)

        alert_id = await db.log_alert(
            rule="extreme_volume_spike",
            priority="HIGH",
            symbol="PEPEUSDT",
            data={"volume_spike": 850.0, "ts": _aware(0)},
        )
        assert alert_id == 42
        sql, *params = conn.fetchrow.await_args.args
        assert "INSERT INTO alert_history" in sql
        # Parameter data harus JSON string yang valid
        data_param = params[3]
        parsed = json.loads(data_param)
        assert parsed["volume_spike"] == 850.0

    @pytest.mark.asyncio
    async def test_get_alert_history_parses_jsonb_string(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {
                "id": 1, "rule": "extreme_volume_spike", "priority": "HIGH",
                "symbol": "PEPEUSDT",
                "data": '{"volume_spike": 850.0}',  # JSONB bisa datang sebagai str
                "timestamp": _aware(0.2),
            },
            {
                "id": 2, "rule": "confirmed_signal", "priority": "HIGH",
                "symbol": "ETHUSDT", "data": {"confirmed": True},
                "timestamp": _aware(0.1),
            },
        ])
        db = _make_db_with_conn(conn)

        history = await db.get_alert_history(limit=10)
        assert len(history) == 2
        # String JSON di-parse menjadi dict
        assert history[0]["data"] == {"volume_spike": 850.0}
        # Dict tetap utuh
        assert history[1]["data"] == {"confirmed": True}

    @pytest.mark.asyncio
    async def test_get_alert_history_clamps_limit(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_history(limit=99999)
        # Limit di-clamp ke 500
        assert conn.fetch.await_args.args[1] == 500


# ====================================================================
# 2. AlertSystem: persistensi rules & callback
# ====================================================================

class TestAlertSystemV24:
    @pytest.mark.asyncio
    async def test_load_persisted_rules_applies_thresholds(self):
        mock_db = _make_mock_db()
        mock_db.get_alert_rule_thresholds.return_value = {
            "extreme_volume_spike": 900.0,
            "confirmed_signal": 0.95,
            "non_editable_rule": 123.0,  # harus diabaikan
        }
        system = AlertSystem(mock_db)
        system._load_default_rules()

        ok = await system.load_persisted_rules()
        assert ok is True
        rules = {r["name"]: r for r in system.alert_rules}
        assert rules["extreme_volume_spike"]["threshold"] == 900.0
        assert rules["confirmed_signal"]["threshold"] == 0.95
        # Rule non-editable tidak tersentuh
        assert rules["smart_money_detected"]["condition"] is not None

    @pytest.mark.asyncio
    async def test_load_persisted_rules_survives_db_failure(self):
        mock_db = _make_mock_db()
        mock_db.get_alert_rule_thresholds.side_effect = ConnectionError("DB down")
        system = AlertSystem(mock_db)
        system._load_default_rules()

        ok = await system.load_persisted_rules()
        assert ok is False
        # Rules tetap ter-load dengan default
        assert len(system.alert_rules) == 4

    @pytest.mark.asyncio
    async def test_persist_rule_threshold_success_and_failure(self):
        mock_db = _make_mock_db()
        system = AlertSystem(mock_db)

        assert await system.persist_rule_threshold("extreme_volume_spike", 700.0) is True
        mock_db.upsert_alert_rule_threshold.assert_awaited_with("extreme_volume_spike", 700.0)

        mock_db.upsert_alert_rule_threshold.side_effect = ConnectionError("down")
        assert await system.persist_rule_threshold("extreme_volume_spike", 700.0) is False

    @pytest.mark.asyncio
    async def test_check_alerts_persists_to_db(self):
        mock_db = _make_mock_db()
        system = AlertSystem(mock_db)
        system._load_default_rules()

        triggered = await system.check_alerts({
            "symbol": "PEPEUSDT",
            "volume_spike": 850.0,  # > default 500
        })
        assert len(triggered) == 1
        assert triggered[0]["rule"] == "extreme_volume_spike"
        mock_db.log_alert.assert_awaited_once()
        kwargs = mock_db.log_alert.await_args.kwargs
        assert kwargs["rule"] == "extreme_volume_spike"
        assert kwargs["priority"] == "HIGH"
        assert kwargs["symbol"] == "PEPEUSDT"

    @pytest.mark.asyncio
    async def test_check_alerts_db_failure_does_not_break_trigger(self):
        """Best-effort persist: DB gagal, alert tetap ter-trigger & tersimpan di memori."""
        mock_db = _make_mock_db()
        mock_db.log_alert.side_effect = ConnectionError("DB down")
        system = AlertSystem(mock_db)
        system._load_default_rules()

        triggered = await system.check_alerts({
            "symbol": "PEPEUSDT", "volume_spike": 850.0,
        })
        assert len(triggered) == 1
        assert len(system.alert_history) == 1

    @pytest.mark.asyncio
    async def test_check_alerts_calls_callback(self):
        mock_db = _make_mock_db()
        system = AlertSystem(mock_db)
        system._load_default_rules()
        callback = AsyncMock()
        system.set_alert_callback(callback)

        await system.check_alerts({
            "symbol": "ETHUSDT", "volume_spike": 650.0,
        })
        callback.assert_awaited_once()
        alert = callback.await_args.args[0]
        assert alert["rule"] == "extreme_volume_spike"
        assert alert["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_callback_failure_does_not_break_trigger(self):
        mock_db = _make_mock_db()
        system = AlertSystem(mock_db)
        system._load_default_rules()
        system.set_alert_callback(AsyncMock(side_effect=RuntimeError("WS broken")))

        triggered = await system.check_alerts({
            "symbol": "ETHUSDT", "volume_spike": 650.0,
        })
        assert len(triggered) == 1


# ====================================================================
# 3. Endpoint v2.4 via HTTP
# ====================================================================

class TestAlertEndpointsV24:
    def test_get_rules_applies_persisted_threshold(self, v24_client):
        mock_db = v24_client._v24_mock_db  # type: ignore[attr-defined]
        mock_db.get_alert_rule_thresholds.return_value = {
            "extreme_volume_spike": 888.0,
        }
        res = v24_client.get("/dashboard/api/alerts/rules")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        rule = next(r for r in data["data"] if r["name"] == "extreme_volume_spike")
        assert rule["threshold"] == 888.0

    def test_put_rule_persists_to_db(self, v24_client):
        mock_db = v24_client._v24_mock_db  # type: ignore[attr-defined]
        res = v24_client.put(
            "/dashboard/api/alerts/rules/extreme_volume_spike",
            json={"threshold": 777.0},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["persisted"] is True
        assert body["data"]["threshold"] == 777.0
        mock_db.upsert_alert_rule_threshold.assert_awaited_with(
            "extreme_volume_spike", 777.0
        )

    def test_history_from_database(self, v24_client):
        mock_db = v24_client._v24_mock_db  # type: ignore[attr-defined]
        mock_db.get_alert_history.return_value = [
            {
                "id": 7, "rule": "extreme_volume_spike", "priority": "HIGH",
                "symbol": "PEPEUSDT", "data": {"volume_spike": 850.0},
                "timestamp": _aware(0.3).isoformat(),
            },
        ]
        res = v24_client.get("/dashboard/api/alerts/history?limit=10")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["source"] == "database"
        assert body["count"] == 1
        assert body["data"][0]["symbol"] == "PEPEUSDT"

    def test_history_falls_back_to_memory_on_db_error(self, v24_client):
        mock_db = v24_client._v24_mock_db  # type: ignore[attr-defined]
        mock_db.get_alert_history.side_effect = ConnectionError("DB down")

        # Isi riwayat in-memory lewat engine singleton
        system = ui_routes.get_alert_system()
        system.alert_history.append({
            "timestamp": _aware(0).isoformat(),
            "rule": "manual_test", "priority": "MEDIUM",
            "symbol": "ETHUSDT", "channels": ["log"], "data": {},
        })

        res = v24_client.get("/dashboard/api/alerts/history")
        assert res.status_code == 200
        body = res.json()
        assert body["source"] == "memory"
        assert body["count"] == 1
        assert body["data"][0]["rule"] == "manual_test"

    def test_history_limit_clamped(self, v24_client):
        res = v24_client.get("/dashboard/api/alerts/history?limit=10000")
        assert res.status_code == 200
        # Tidak crash; mock db menerima limit hasil clamp (<=200)
        mock_db = v24_client._v24_mock_db  # type: ignore[attr-defined]
        assert mock_db.get_alert_history.await_args.kwargs["limit"] <= 200


# ====================================================================
# 4. Integrasi pipeline: _handle_anomaly -> check_alerts -> broadcast
# ====================================================================

class TestPipelineIntegrationV24:
    @pytest.mark.asyncio
    async def test_handle_anomaly_triggers_alert_and_broadcasts(self):
        """Anomaly dengan spike tinggi harus:
        1) memicu alert rule -> 2) persist ke DB -> 3) broadcast alert_triggered.
        """
        from app.main import CryptoOracleApp

        mock_db = _make_mock_db()
        analyzer = MagicMock()
        analyzer.analyze_anomaly = AsyncMock(return_value={
            "symbol": "PEPEUSDT", "confirmed": False,
            "confidence_score": 0.4, "news_sentiment": "neutral",
        })
        notifier = MagicMock()
        notifier.send_signal = AsyncMock()

        app = CryptoOracleApp.__new__(CryptoOracleApp)
        app.settings = MagicMock()
        app.db = None
        app.streamer = None
        app.analyzer = analyzer
        app.notifier = notifier
        app.running = False
        app.started_at = 0.0
        app._background_tasks = set()

        # Real AlertSystem (rules default) dengan mock db
        system = AlertSystem(mock_db)
        system._load_default_rules()
        system.set_alert_callback(app._broadcast_alert)

        fake_ws = MagicMock()
        fake_ws.send_text = AsyncMock()
        with patch("app.main.get_alert_system", return_value=system), \
             patch("app.ui.routes.active_connections", [fake_ws]):
            await app._handle_anomaly({
                "symbol": "PEPEUSDT", "price": 0.000012,
                "volume_spike": 950.0,
            })

        # Alert ter-trigger + persist
        mock_db.log_alert.assert_awaited()
        # WS broadcast berisi type alert_triggered
        fake_ws.send_text.assert_awaited()
        sent = json.loads(fake_ws.send_text.await_args.args[0])
        assert sent["type"] == "alert_triggered"
        assert sent["data"]["symbol"] == "PEPEUSDT"
        assert sent["data"]["rule"] == "extreme_volume_spike"
        assert sent["data"]["priority"] == "HIGH"

    @pytest.mark.asyncio
    async def test_handle_anomaly_no_alert_below_threshold(self):
        from app.main import CryptoOracleApp

        mock_db = _make_mock_db()
        analyzer = MagicMock()
        analyzer.analyze_anomaly = AsyncMock(return_value={
            "symbol": "BTCUSDT", "confirmed": False,
            "confidence_score": 0.1, "news_sentiment": "neutral",
            "smart_money_detected": False,
        })
        notifier = MagicMock()
        notifier.send_signal = AsyncMock()

        app = CryptoOracleApp.__new__(CryptoOracleApp)
        app.settings = MagicMock()
        app.db = None
        app.streamer = None
        app.analyzer = analyzer
        app.notifier = notifier
        app.running = False
        app.started_at = 0.0
        app._background_tasks = set()

        system = AlertSystem(mock_db)
        system._load_default_rules()
        system.set_alert_callback(AsyncMock())

        with patch("app.main.get_alert_system", return_value=system):
            await app._handle_anomaly({
                "symbol": "BTCUSDT", "price": 60000.0,
                "volume_spike": 10.0,
            })

        mock_db.log_alert.assert_not_awaited()
        system.on_alert.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_alert_evaluation_failure_does_not_stop_pipeline(self):
        """Alert engine error tidak boleh memutus alur notifikasi sinyal."""
        from app.main import CryptoOracleApp

        mock_db = _make_mock_db()
        analyzer = MagicMock()
        analyzer.analyze_anomaly = AsyncMock(return_value={
            "symbol": "ETHUSDT", "confirmed": True,
            "confidence_score": 0.9, "news_sentiment": "positive",
        })
        notifier = MagicMock()
        notifier.send_signal = AsyncMock()

        app = CryptoOracleApp.__new__(CryptoOracleApp)
        app.settings = MagicMock()
        app.db = None
        app.streamer = None
        app.analyzer = analyzer
        app.notifier = notifier
        app.running = False
        app.started_at = 0.0
        app._background_tasks = set()

        broken_system = MagicMock()
        broken_system.check_alerts = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("app.main.get_alert_system", return_value=broken_system):
            await app._handle_anomaly({
                "symbol": "ETHUSDT", "price": 3000.0,
                "volume_spike": 400.0,
            })

        # Pipeline tetap lanjut: notifikasi sinyal terkirim
        notifier.send_signal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_wires_alert_callback(self):
        """initialize() harus memasang callback broadcast ke AlertSystem."""
        from app.main import CryptoOracleApp

        mock_db = _make_mock_db()
        analyzer = MagicMock()
        analyzer.start = AsyncMock()
        notifier = MagicMock()
        notifier.start = AsyncMock()

        with patch("app.main.get_database", new_callable=AsyncMock, return_value=mock_db), \
             patch("app.main.TelegramNotifier", return_value=notifier), \
             patch("app.main.DeepDiveAnalyzer", return_value=analyzer), \
             patch("app.main.BinanceStreamer") as streamer_cls, \
             patch("app.main.get_alert_system", return_value=_make_mock_db()) as mock_get_alerts:

            app = CryptoOracleApp()
            await app.initialize()

        mock_get_alerts.assert_called_once()
        alert_system = mock_get_alerts.return_value
        alert_system.set_alert_callback.assert_called_once()
        # Callback adalah bound method _broadcast_alert
        cb = alert_system.set_alert_callback.call_args.args[0]
        assert callable(cb)
