"""
Tests untuk fitur Dashboard v2.10:
- DB: tabel webhook_outbox (enqueue/get/count/delete/record_attempt/prune)
  + agregasi kesehatan delivery (get_webhook_health) + rule-stats harian
  (get_alert_rule_stats_daily)
- Endpoint GET /api/alerts/rule-stats?bucket=day (zero-fill harian, clamp)
- Endpoint GET /api/webhook/health (DB + fallback memory + outbox_pending)
- Endpoint GET /api/webhook/outbox + POST /api/webhook/outbox/replay
  (not_configured / kosong / sukses hapus / gagal tetap antre + log replay)
- Pipeline main.py: dispatch gagal -> masuk outbox; _replay_outbox_once
- Guard HTML v2.10: outbox/health/seg elemen, rule author [hidden] utk
  elemen flex/grid baru, wiring, palette, footer, unicode escape valid
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app.notifier import WebhookDispatcher
from app import runtime_settings as rs
from app.ui import routes as ui_routes
from app.ui.rate_limit import reset_all_limiters

# Selector atribut valid dibangun via konkatenasi (pelajaran ronde-7/8)
HIDDEN_SEL = "[" + "hidden]"


def _make_db_with_conn(conn: MagicMock) -> app_database.Database:
    db = app_database.Database()
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    db.pool = pool
    db._initialized = True
    return db


@pytest.fixture
def v210_client():
    """TestClient + mock DB global untuk endpoint v2.10."""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = MagicMock()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

        mock_global_db.get_alert_history = AsyncMock(return_value=[])
        mock_global_db.get_alert_rule_stats = AsyncMock(return_value=[])
        mock_global_db.get_alert_rule_stats_daily = AsyncMock(return_value=[])
        mock_global_db.get_alert_rule_thresholds = AsyncMock(return_value={})
        mock_global_db.upsert_alert_rule_threshold = AsyncMock(return_value=None)
        mock_global_db.get_recent_signals = AsyncMock(return_value=[])
        mock_global_db.get_recent_anomalies = AsyncMock(return_value=[])
        mock_global_db.get_system_stats = AsyncMock(return_value={
            "total_signals": 0, "signals_24h": 0, "total_anomalies": 0,
            "smart_wallets_count": 0, "success_rate": 0.0, "uptime_hours": 0,
        })
        mock_global_db.get_symbol_summary = AsyncMock(return_value=[])
        mock_global_db.get_price_history = AsyncMock(return_value=[])
        mock_global_db.get_alert_heatmap = AsyncMock(return_value=[])
        mock_global_db.get_alert_history_stats = AsyncMock(
            return_value={"total_alerts": 0, "oldest_alert": None}
        )
        mock_global_db.prune_alert_history = AsyncMock(return_value=0)
        mock_global_db.prune_webhook_deliveries = AsyncMock(return_value=0)
        mock_global_db.prune_webhook_outbox = AsyncMock(return_value=0)
        mock_global_db.get_app_settings = AsyncMock(return_value={})
        mock_global_db.set_app_setting = AsyncMock()
        mock_global_db.log_webhook_delivery = AsyncMock(return_value=1)
        mock_global_db.get_webhook_deliveries = AsyncMock(return_value=[])
        mock_global_db.get_webhook_health = AsyncMock(return_value={
            "window_hours": 24, "total": 5, "ok": 4, "fail": 1,
            "success_rate": 80.0, "avg_duration_ms": 250,
            "avg_attempts": 1.4, "last_fail_reason": "http_503",
        })
        mock_global_db.get_webhook_outbox = AsyncMock(return_value=[])
        mock_global_db.count_webhook_outbox = AsyncMock(return_value=0)
        mock_global_db.delete_webhook_outbox = AsyncMock(return_value=0)
        mock_global_db.record_outbox_attempt = AsyncMock()
        mock_global_db.enqueue_webhook_outbox = AsyncMock(return_value=1)
        mock_global_db._initialized = True

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        reset_all_limiters()
        ui_routes.reset_engines()
        rs._cache.clear()
        ui_routes.set_webhook(None)

        from app.main import app
        with TestClient(app) as test_client:
            ui_routes.set_notifier(None)
            test_client._v210_mock_db = mock_global_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()
        rs._cache.clear()
        ui_routes.set_webhook(None)


# ====================================================================
# 1. DB layer: webhook_outbox
# ====================================================================

class TestWebhookOutboxDb:
    async def test_enqueue_webhook_outbox(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 3})
        db = _make_db_with_conn(conn)

        payload = {"source": "z-capital", "alert": {"rule": "r", "symbol": "S"}}
        rid = await db.enqueue_webhook_outbox(
            payload=payload, rule="r", symbol="S",
            attempts=3, last_reason="http_503",
        )
        assert rid == 3
        sql, *params = conn.fetchrow.await_args.args
        assert "INSERT INTO webhook_outbox" in sql
        assert json.loads(params[0]) == payload  # diserialisasi JSON valid
        assert params[1] == "r"
        assert params[2] == "S"
        assert params[3] == 3
        assert params[4] == "http_503"

    async def test_enqueue_attempts_clamped_and_truncation(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 1})
        db = _make_db_with_conn(conn)

        await db.enqueue_webhook_outbox(
            payload={}, rule="r" * 500, symbol="S" * 500,
            attempts=-5, last_reason="x" * 500,
        )
        _, *params = conn.fetchrow.await_args.args
        assert len(params[1]) == 100   # rule dipotong
        assert len(params[2]) == 50    # symbol dipotong
        assert params[3] == 0          # attempts negatif -> 0
        assert len(params[4]) == 100   # reason dipotong

    async def test_enqueue_db_failure_returns_none(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
        db = _make_db_with_conn(conn)
        assert await db.enqueue_webhook_outbox(payload={}) is None

    async def test_get_webhook_outbox_oldest_first_and_clamp(self):
        conn = MagicMock()
        rows = [
            {"id": 1, "payload": {}, "rule": "a", "symbol": "A",
             "attempts": 1, "last_reason": "timeout",
             "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
             "last_attempt_at": None},
            {"id": 2, "payload": {}, "rule": "b", "symbol": "B",
             "attempts": 0, "last_reason": None,
             "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
             "last_attempt_at": None},
        ]
        conn.fetch = AsyncMock(return_value=rows)
        db = _make_db_with_conn(conn)

        got = await db.get_webhook_outbox(limit=999)
        sql, param = conn.fetch.await_args.args
        assert "ORDER BY created_at ASC, id ASC" in sql  # terlama dulu
        assert param == 200  # clamp 999 -> 200
        assert [g["id"] for g in got] == [1, 2]

    async def test_count_webhook_outbox(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=7)
        db = _make_db_with_conn(conn)
        assert await db.count_webhook_outbox() == 7

    async def test_delete_webhook_outbox(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 2")
        db = _make_db_with_conn(conn)
        assert await db.delete_webhook_outbox([1, 2, 3]) == 2
        sql, param = conn.execute.await_args.args
        assert "DELETE FROM webhook_outbox WHERE id = ANY($1)" in sql
        assert param == [1, 2, 3]

    async def test_delete_webhook_outbox_empty_noop(self):
        db = _make_db_with_conn(MagicMock())
        assert await db.delete_webhook_outbox([]) == 0

    async def test_record_outbox_attempt(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="UPDATE 2")
        db = _make_db_with_conn(conn)
        await db.record_outbox_attempt([5, 6], reason="http_503")
        sql, p1, p2 = conn.execute.await_args.args
        assert "attempts = attempts + 1" in sql
        assert p1 == [5, 6]
        assert p2 == "http_503"

    async def test_prune_webhook_outbox(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 4")
        db = _make_db_with_conn(conn)
        assert await db.prune_webhook_outbox(7) == 4
        # 0 hari = noop tanpa menyentuh DB
        conn2 = MagicMock()
        db2 = _make_db_with_conn(conn2)
        assert await db2.prune_webhook_outbox(0) == 0
        conn2.execute.assert_not_called()


# ====================================================================
# 2. DB layer: health aggregation + rule stats harian
# ====================================================================

class TestWebhookHealthDb:
    async def test_get_webhook_health_parses_row(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "total": 10, "ok": 8, "fail": 2,
            "avg_duration_ms": 150.5, "avg_attempts": 1.25,
        })
        conn.fetchval = AsyncMock(return_value="timeout")
        db = _make_db_with_conn(conn)

        h = await db.get_webhook_health(hours=24)
        assert h["total"] == 10
        assert h["ok"] == 8
        assert h["fail"] == 2
        assert h["success_rate"] == 80.0
        assert h["avg_duration_ms"] == 150
        assert h["avg_attempts"] == 1.25
        assert h["last_fail_reason"] == "timeout"
        sql, param = conn.fetchrow.await_args.args
        assert "make_interval(hours => $1)" in sql
        assert param == 24

    async def test_get_webhook_health_empty_window(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "total": 0, "ok": 0, "fail": 0,
            "avg_duration_ms": None, "avg_attempts": None,
        })
        conn.fetchval = AsyncMock(return_value=None)
        db = _make_db_with_conn(conn)
        h = await db.get_webhook_health()
        assert h["total"] == 0
        assert h["success_rate"] is None
        assert h["last_fail_reason"] is None

    async def test_get_webhook_health_clamps_window(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "total": 1, "ok": 1, "fail": 0,
            "avg_duration_ms": None, "avg_attempts": None,
        })
        conn.fetchval = AsyncMock(return_value=None)
        db = _make_db_with_conn(conn)
        await db.get_webhook_health(hours=9999)
        _, param = conn.fetchrow.await_args.args
        assert param == 720  # clamp maksimum


class TestRuleStatsDailyDb:
    async def test_get_alert_rule_stats_daily_groups_by_day(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {"rule": "r1", "day": datetime(2026, 1, 1, tzinfo=timezone.utc),
             "count": 2, "severity": 2},
        ])
        db = _make_db_with_conn(conn)
        rows = await db.get_alert_rule_stats_daily(days=7)
        sql, param = conn.fetch.await_args.args
        assert "date_trunc('day', timestamp)" in sql
        assert "make_interval(days => $1)" in sql
        assert param == 7
        assert rows[0]["count"] == 2

    async def test_get_alert_rule_stats_daily_clamps_days(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)
        await db.get_alert_rule_stats_daily(days=999)
        _, param = conn.fetch.await_args.args
        assert param == 30


# ====================================================================
# 3. Endpoint rule-stats bucket=day
# ====================================================================

class TestRuleStatsBucketDay:
    def test_bucket_day_zero_fill(self, v210_client):
        db = v210_client._v210_mock_db
        now = datetime.now(timezone.utc)
        db.get_alert_rule_stats_daily = AsyncMock(return_value=[
            {"rule": "extreme_volume_spike",
             "day": (now - timedelta(days=1)).replace(
                 hour=0, minute=0, second=0, microsecond=0),
             "count": 3, "severity": 2},
        ])
        res = v210_client.get("/dashboard/api/alerts/rule-stats?hours=7&bucket=day")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["bucket"] == "day"
        assert body["count"] == 1
        entry = body["data"][0]
        assert entry["total"] == 3
        assert len(entry["buckets"]) == 7  # window 7 hari zero-filled
        counts = [b["count"] for b in entry["buckets"]]
        assert sum(counts) == 3
        assert "day" in entry["buckets"][0]  # key slot = 'day'
        assert entry["last_fired"] is not None

    def test_bucket_day_clamps_to_30(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_alert_rule_stats_daily = AsyncMock(return_value=[])
        res = v210_client.get("/dashboard/api/alerts/rule-stats?hours=99&bucket=day")
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        assert db.get_alert_rule_stats_daily.await_args.kwargs["days"] == 30

    def test_bucket_invalid_falls_back_to_hour(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_alert_rule_stats = AsyncMock(return_value=[])
        res = v210_client.get("/dashboard/api/alerts/rule-stats?hours=24&bucket=week")
        assert res.status_code == 200
        body = res.json()
        assert body["bucket"] == "hour"
        db.get_alert_rule_stats.assert_awaited_once()

    def test_bucket_hour_default_unchanged(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_alert_rule_stats = AsyncMock(return_value=[])
        res = v210_client.get("/dashboard/api/alerts/rule-stats?hours=168")
        assert res.status_code == 200
        body = res.json()
        assert body["bucket"] == "hour"
        assert db.get_alert_rule_stats.await_args.kwargs["hours"] == 168


# ====================================================================
# 4. Endpoint /api/webhook/health
# ====================================================================

class TestWebhookHealthEndpoint:
    def test_health_from_database_with_pending(self, v210_client):
        db = v210_client._v210_mock_db
        db.count_webhook_outbox = AsyncMock(return_value=4)
        res = v210_client.get("/dashboard/api/webhook/health?hours=24")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["source"] == "database"
        h = body["data"]
        assert h["total"] == 5
        assert h["success_rate"] == 80.0
        assert h["outbox_pending"] == 4  # gabungan count outbox
        assert h["last_fail_reason"] == "http_503"

    def test_health_memory_fallback(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_webhook_health = AsyncMock(side_effect=RuntimeError("db down"))
        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        )
        ui_routes.set_webhook(dispatcher)
        # paksa hasil dispatch tersimpan di last_result
        asyncio.get_event_loop_policy()
        result = asyncio.run(dispatcher.test_send())
        assert result["ok"] is True

        res = v210_client.get("/dashboard/api/webhook/health?hours=24")
        assert res.status_code == 200
        body = res.json()
        assert body["source"] == "memory"
        assert body["data"]["total"] == 1
        assert body["data"]["success_rate"] == 100.0
        assert body["data"]["outbox_pending"] == 0  # count DB gagal -> 0

    def test_health_invalid_hours(self, v210_client):
        # Nilai negatif dibatasi (clamp) di dalam endpoint/DB, tidak raise:
        # endpoint harus tetap sukses dengan nilai jendela yang masuk akal.
        res = v210_client.get("/dashboard/api/webhook/health?hours=-5")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["data"]["window_hours"] >= 1


# ====================================================================
# 5. Endpoint /api/webhook/outbox + replay
# ====================================================================

class TestWebhookOutboxEndpoint:
    def test_outbox_list_shape(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_webhook_outbox = AsyncMock(return_value=[{
            "id": 9, "payload": {"alert": {"secret": "SHOULD_NOT_LEAK"}},
            "rule": "extreme_volume_spike", "symbol": "PEPEUSDT",
            "attempts": 3, "last_reason": "http_503",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "last_attempt_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        }])
        res = v210_client.get("/dashboard/api/webhook/outbox")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["count"] == 1
        item = body["data"][0]
        assert item["id"] == 9
        assert item["rule"] == "extreme_volume_spike"
        assert item["symbol"] == "PEPEUSDT"
        assert item["last_reason"] == "http_503"
        assert item["queued_at"].startswith("2026-01-01")
        # payload TIDAK bocor ke dashboard
        assert "payload" not in item
        assert "SHOULD_NOT_LEAK" not in res.text

    def test_outbox_replay_not_configured(self, v210_client):
        res = v210_client.post("/dashboard/api/webhook/outbox/replay")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["reason"] == "not_configured"
        assert body["replayed"] == 0

    def test_outbox_replay_empty(self, v210_client):
        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        )
        ui_routes.set_webhook(dispatcher)
        res = v210_client.post("/dashboard/api/webhook/outbox/replay")
        assert res.status_code == 200
        body = res.json()
        assert body["replayed"] == 0
        assert body["remaining"] == 0
        assert "empty" in body["message"].lower()

    def test_outbox_replay_success_clears_and_logs(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_webhook_outbox = AsyncMock(return_value=[
            {"id": 1, "payload": {"alert": {"rule": "r1", "symbol": "AAA"}},
             "rule": "r1", "symbol": "AAA", "attempts": 2,
             "last_reason": "timeout", "created_at": None,
             "last_attempt_at": None},
            {"id": 2, "payload": {"alert": {"rule": "r2", "symbol": "BBB"}},
             "rule": "r2", "symbol": "BBB", "attempts": 1,
             "last_reason": "timeout", "created_at": None,
             "last_attempt_at": None},
        ])
        db.delete_webhook_outbox = AsyncMock(return_value=2)
        db.count_webhook_outbox = AsyncMock(return_value=0)
        db.log_webhook_delivery = AsyncMock(return_value=1)

        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        )
        ui_routes.set_webhook(dispatcher)

        res = v210_client.post("/dashboard/api/webhook/outbox/replay")
        assert res.status_code == 200
        body = res.json()
        assert body["replayed"] == 2
        assert body["sent"] == 2
        assert body["failed"] == 0
        assert body["remaining"] == 0
        # keduanya dihapus dari antrean
        assert db.delete_webhook_outbox.await_args.args[0] == [1, 2]
        # delivery replay tercatat ke log audit
        assert db.log_webhook_delivery.await_count == 2
        kwargs = db.log_webhook_delivery.await_args.kwargs
        assert kwargs["event"] == "replay"
        assert kwargs["ok"] is True
        assert kwargs["symbol"] in {"AAA", "BBB"}

    def test_outbox_replay_mixed_failure_stays_queued(self, v210_client):
        db = v210_client._v210_mock_db
        db.get_webhook_outbox = AsyncMock(return_value=[
            {"id": 1, "payload": {"alert": {"rule": "r1", "symbol": "AAA"}},
             "rule": "r1", "symbol": "AAA", "attempts": 0,
             "last_reason": None, "created_at": None, "last_attempt_at": None},
            {"id": 2, "payload": {"alert": {"rule": "r2", "symbol": "BBB"}},
             "rule": "r2", "symbol": "BBB", "attempts": 0,
             "last_reason": None, "created_at": None, "last_attempt_at": None},
        ])
        db.delete_webhook_outbox = AsyncMock(return_value=1)
        db.count_webhook_outbox = AsyncMock(return_value=1)

        # 2xx -> sukses, 503 -> gagal total (retry 1x agar test cepat)
        calls = {"n": 0}

        def transport(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200 if calls["n"] == 1 else 503)

        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(transport),
            max_attempts=1,
        )
        ui_routes.set_webhook(dispatcher)

        res = v210_client.post("/dashboard/api/webhook/outbox/replay")
        assert res.status_code == 200
        body = res.json()
        assert body["replayed"] == 2
        assert body["sent"] == 1
        assert body["failed"] == 1
        assert body["remaining"] == 1
        assert body["last_reason"] == "http_503"
        # hanya id sukses yang dihapus
        assert db.delete_webhook_outbox.await_args.args[0] == [1]
        # gagal dicatat attempts +1 dengan reason terakhir
        # (routes.py memanggil record_outbox_attempt(ids, reason) posisi)
        rec_args = db.record_outbox_attempt.await_args.args
        assert rec_args[0] == [2]
        assert rec_args[1] == "http_503"


# ====================================================================
# 6. Pipeline main.py: gagal dispatch -> outbox; replay loop
# ====================================================================

class TestPipelineOutboxEnqueue:
    @pytest.fixture
    def oracle_with_db(self):
        with patch("app.main.get_database", new_callable=AsyncMock), \
             patch("app.main.BinanceStreamer"), \
             patch("app.main.TelegramNotifier"), \
             patch("app.main.DeepDiveAnalyzer"):
            from app.main import CryptoOracleApp
            app = CryptoOracleApp()
            app.db = MagicMock()
            app.db.log_webhook_delivery = AsyncMock(return_value=1)
            app.db.enqueue_webhook_outbox = AsyncMock(return_value=10)
            app.db.get_webhook_outbox = AsyncMock(return_value=[])
            app.db.delete_webhook_outbox = AsyncMock(return_value=0)
            app.db.record_outbox_attempt = AsyncMock()
            yield app

    async def test_failed_dispatch_enqueues_outbox(self, oracle_with_db):
        app = oracle_with_db

        def transport(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(transport),
            max_attempts=2, backoff_seconds=0,
        )
        alert = {
            "rule": "extreme_volume_spike", "priority": "HIGH",
            "symbol": "PEPEUSDT", "channels": ["dashboard"],
            "timestamp": "2026-01-01T00:00:00+00:00",
            "data": {"volume_spike": 900, "confidence_score": 0.9},
        }
        await app._dispatch_webhook_and_log(dispatcher, alert)

        app.db.log_webhook_delivery.assert_awaited_once()
        kwargs = app.db.log_webhook_delivery.await_args.kwargs
        assert kwargs["ok"] is False
        assert kwargs["event"] == "alert"

        app.db.enqueue_webhook_outbox.assert_awaited_once()
        ek = app.db.enqueue_webhook_outbox.await_args.kwargs
        assert ek["rule"] == "extreme_volume_spike"
        assert ek["symbol"] == "PEPEUSDT"
        assert ek["last_reason"] == "http_500"
        payload = ek["payload"]
        assert payload["type"] == "alert.triggered"
        assert payload["alert"]["rule"] == "extreme_volume_spike"

    async def test_successful_dispatch_skips_outbox(self, oracle_with_db):
        app = oracle_with_db
        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        )
        await app._dispatch_webhook_and_log(
            dispatcher,
            {"rule": "r", "priority": "LOW", "symbol": "S",
             "channels": [], "timestamp": None, "data": {}},
        )
        app.db.enqueue_webhook_outbox.assert_not_called()

    async def test_replay_outbox_once_success_and_fail(self, oracle_with_db):
        app = oracle_with_db
        calls = {"n": 0}

        def transport(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200 if calls["n"] == 1 else 503)

        dispatcher = WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(transport),
            max_attempts=1,
        )
        ui_routes.set_webhook(dispatcher)

        app.db.get_webhook_outbox = AsyncMock(return_value=[
            {"id": 1, "payload": {"alert": {"rule": "r1", "symbol": "AAA"}},
             "rule": "r1", "symbol": "AAA", "attempts": 0,
             "last_reason": None, "created_at": None, "last_attempt_at": None},
            {"id": 2, "payload": {"alert": {"rule": "r2", "symbol": "BBB"}},
             "rule": "r2", "symbol": "BBB", "attempts": 0,
             "last_reason": None, "created_at": None, "last_attempt_at": None},
        ])

        summary = await app._replay_outbox_once(batch=20)
        assert summary == {"queued": 2, "sent": 1, "failed": 1}
        app.db.delete_webhook_outbox.assert_awaited_once_with([1])
        app.db.record_outbox_attempt.assert_awaited_once()

    async def test_replay_outbox_once_not_configured_noop(self, oracle_with_db):
        app = oracle_with_db
        ui_routes.set_webhook(None)
        summary = await app._replay_outbox_once()
        assert summary == {"queued": 0, "sent": 0, "failed": 0}
        app.db.get_webhook_outbox.assert_not_called()

    async def test_replay_outbox_once_empty(self, oracle_with_db):
        app = oracle_with_db
        ui_routes.set_webhook(WebhookDispatcher(
            url="https://hooks.example.com/x",
            transport=httpx.MockTransport(lambda req: httpx.Response(200)),
        ))
        app.db.get_webhook_outbox = AsyncMock(return_value=[])
        summary = await app._replay_outbox_once()
        assert summary == {"queued": 0, "sent": 0, "failed": 0}

    async def test_retention_prunes_outbox(self, oracle_with_db):
        app = oracle_with_db
        app.db.prune_alert_history = AsyncMock(return_value=0)
        app.db.prune_webhook_deliveries = AsyncMock(return_value=0)
        app.db.prune_webhook_outbox = AsyncMock(return_value=3)
        app.settings = MagicMock()
        app.settings.alert_history_retention_days = 7
        with patch("app.main.runtime_settings") as mock_rs:
            mock_rs.get_int = MagicMock(return_value=7)
            deleted = await app._prune_alert_history_once()
        assert deleted == 0
        app.db.prune_webhook_outbox.assert_awaited_once_with(7)


# ====================================================================
# 7. Guard HTML v2.10
# ====================================================================

class TestDashboardHtmlV210:
    def _html(self):
        with open("app/ui/templates/dashboard.html", encoding="utf-8") as f:
            return f.read()

    def test_outbox_panel_elements(self):
        html = self._html()
        for elem_id in ("wh-outbox", "wh-out-head", "wh-out-list",
                        "wh-out-count", "wh-replay-btn"):
            assert f'id="{elem_id}"' in html

    def test_health_card_elements(self):
        html = self._html()
        for elem_id in ("wh-health", "wh-rate-value", "wh-rate-fill",
                        "wh-total-value", "wh-lat-value", "wh-att-value"):
            assert f'id="{elem_id}"' in html

    def test_audit_window_segmented(self):
        html = self._html()
        assert 'id="audit-window-seg"' in html
        assert 'data-window="24h"' in html
        assert 'data-window="7d"' in html
        assert "aria-pressed" in html

    def test_new_hidden_elements_have_author_rules(self):
        """Regresi v2.8/v2.9: display:flex/grid menimpa rule UA [hidden]."""
        html = self._html()
        residual = html.replace(HIDDEN_SEL, "@@OK@@")
        assert not [m for m in
                    ["wh-healthidden]", "wh-out-listidden]"] if m in residual]
        assert ".wh-health" + HIDDEN_SEL in html
        assert ".wh-out-list" + HIDDEN_SEL in html

    def test_js_functions_defined(self):
        html = self._html()
        for fn in ("loadWebhookHealth", "loadWebhookOutbox", "replayOutbox",
                   "toggleOutbox", "syncHistoryToUrl", "restoreHistoryFromUrl"):
            assert f"function {fn}" in html

    def test_init_wires_new_loaders(self):
        html = self._html()
        assert "loadWebhookHealth();" in html
        assert "loadWebhookOutbox();" in html
        assert "restoreHistoryFromUrl();" in html
        # restore URL dilakukan SEBELUM loadAlertHistory (blok Init saja)
        init_block = html[html.index("// ===== Init ====="):
                         html.index("addLog('Dashboard initialized')")]
        assert init_block.index("restoreHistoryFromUrl();") < \
            init_block.index("loadAlertHistory();")

    def test_palette_has_new_actions(self):
        html = self._html()
        assert "Replay failed webhook deliveries" in html
        assert "Toggle webhook outbox panel" in html
        assert "Toggle audit window" in html

    def test_no_invalid_unicode_escapes(self):
        html = self._html()
        import re
        bad = re.findall(r"\\u(?![0-9a-fA-F]{4})[0-9a-zA-Z]{0,5}", html)
        assert not bad, f"invalid unicode escape: {bad[:5]}"

    def test_footer_version_bumped(self):
        html = self._html()
        assert "Crypto Oracle AI v2." in html  # v2.10+ allowed

    def test_history_filters_sync_to_url(self):
        html = self._html()
        assert "syncHistoryToUrl();" in html
        # replaceState dipakai (bukan pushState) agar tidak spam history
        assert "history.replaceState" in html
