"""
Tests untuk fitur Dashboard v2.9:
- DB: tabel webhook_deliveries (log/get/prune) + filter priority di
  get_alert_history
- WebhookDispatcher retry/backoff: attempts + duration_ms, sukses setelah
  retry, gagal habis percobaan, clamp max_attempts
- Endpoint GET /api/webhook/deliveries (DB + fallback memory) dan
  POST /api/webhook/test yang mencatat delivery
- Endpoint GET /api/alerts/history?priority=...
- Settings export/import: secret-safe (plaintext ditolak, blob enc:v1
  diterima, blob kunci lain ditolak), status per-item, side-effect
  webhook_url ke dispatcher runtime
- Guard HTML v2.9: elemen baru, wiring, footer, selector hidden valid,
  rule author .history-item[hidden]
"""
import asyncio
import json
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

WEBHOOK_FULL_URL = "https://hooks.example.com/TOKEN123/abc"


def _make_db_with_conn(conn: MagicMock) -> app_database.Database:
    db = app_database.Database()
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    db.pool = pool
    db._initialized = True
    return db


@pytest.fixture
def v29_client():
    """TestClient + mock DB global untuk endpoint v2.9."""
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
        mock_global_db.get_app_settings = AsyncMock(return_value={})
        mock_global_db.set_app_setting = AsyncMock()
        mock_global_db.log_webhook_delivery = AsyncMock(return_value=1)
        mock_global_db.get_webhook_deliveries = AsyncMock(return_value=[])
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
            test_client._v29_mock_db = mock_global_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()
        rs._cache.clear()
        ui_routes.set_webhook(None)


# ====================================================================
# 1. DB layer: webhook_deliveries + priority filter
# ====================================================================

class TestWebhookDeliveriesDb:
    @pytest.mark.asyncio
    async def test_log_webhook_delivery(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 7})
        db = _make_db_with_conn(conn)

        rid = await db.log_webhook_delivery(
            event="test", ok=False, status_code=500, reason="http_500",
            attempts=3, duration_ms=1234, rule="extreme_volume_spike",
            symbol="PEPEUSDT",
        )
        assert rid == 7
        sql, *params = conn.fetchrow.await_args.args
        assert "INSERT INTO webhook_deliveries" in sql
        assert params[0] == "test"
        assert params[1] is False
        assert params[2] == 500
        assert params[3] == "http_500"
        assert params[4] == 3
        assert params[5] == 1234
        assert params[6] == "extreme_volume_spike"
        assert params[7] == "PEPEUSDT"

    @pytest.mark.asyncio
    async def test_log_webhook_delivery_truncates_reason(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"id": 1})
        db = _make_db_with_conn(conn)

        await db.log_webhook_delivery(event="alert" * 20, ok=True, reason="x" * 500)
        sql, *params = conn.fetchrow.await_args.args
        assert len(params[0]) <= 20
        assert params[3] is not None and len(params[3]) <= 100

    @pytest.mark.asyncio
    async def test_get_webhook_deliveries_limit_clamp(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_webhook_deliveries(limit=99999)
        sql, params = conn.fetch.await_args.args
        assert params == 200
        await db.get_webhook_deliveries(limit=0)
        assert conn.fetch.await_args.args[1] == 1

    @pytest.mark.asyncio
    async def test_prune_webhook_deliveries(self):
        conn = MagicMock()
        db = _make_db_with_conn(conn)

        conn.execute = AsyncMock(return_value="DELETE 4")
        assert await db.prune_webhook_deliveries(7) == 4
        sql, params = conn.execute.await_args.args
        assert "DELETE FROM webhook_deliveries" in sql
        assert params == 7

        conn.execute = AsyncMock(return_value="DELETE 0")
        assert await db.prune_webhook_deliveries(7) == 0
        # 0 hari -> tidak menjalankan DELETE
        conn.execute = AsyncMock()
        assert await db.prune_webhook_deliveries(0) == 0
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_alert_history_priority_filter(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_history(limit=10, priority="HIGH")
        sql, *rest = conn.fetch.await_args.args
        assert "LOWER(priority) = $1" in sql
        assert rest[0] == "high"  # dinormalisasi lowercase


# ====================================================================
# 2. WebhookDispatcher retry/backoff
# ====================================================================

class TestDispatcherRetry:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200)

        d = WebhookDispatcher(WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler))
        result = await d.dispatch()
        assert result["ok"] is True
        assert result["attempts"] == 1
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(500)
            return httpx.Response(200)

        d = WebhookDispatcher(
            WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler),
            backoff_seconds=0.01,
        )
        result = await d.dispatch()
        assert result["ok"] is True
        assert result["attempts"] == 2
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_retries_exhausted(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503)

        d = WebhookDispatcher(
            WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler),
            max_attempts=3, backoff_seconds=0.01,
        )
        result = await d.dispatch()
        assert result["ok"] is False
        assert result["reason"] == "http_503"
        assert result["attempts"] == 3
        assert calls["n"] == 3
        assert d.last_result == result

    @pytest.mark.asyncio
    async def test_max_attempts_clamped(self):
        d = WebhookDispatcher(WEBHOOK_FULL_URL, max_attempts=99)
        assert d.max_attempts == 5
        d2 = WebhookDispatcher(WEBHOOK_FULL_URL, max_attempts=0)
        assert d2.max_attempts == 1

    @pytest.mark.asyncio
    async def test_not_configured_has_zero_attempts(self):
        d = WebhookDispatcher("")
        result = await d.dispatch()
        assert result["ok"] is False
        assert result["reason"] == "not_configured"
        assert result["attempts"] == 0


# ====================================================================
# 3. Endpoint deliveries + test logging
# ====================================================================

class TestDeliveriesEndpoint:
    def test_deliveries_empty(self, v29_client):
        resp = v29_client.get("/dashboard/api/webhook/deliveries")
        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "success"
        assert body["source"] == "database"
        assert body["data"] == []
        assert body["count"] == 0

    def test_deliveries_rows_serialized(self, v29_client):
        db = v29_client._v29_mock_db
        from datetime import datetime, timezone
        db.get_webhook_deliveries = AsyncMock(return_value=[{
            "id": 3, "event": "alert", "ok": False, "status_code": 500,
            "reason": "http_500", "attempts": 3, "duration_ms": 456,
            "rule": "extreme_volume_spike", "symbol": "PEPEUSDT",
            "created_at": datetime.now(timezone.utc),
        }])
        resp = v29_client.get("/dashboard/api/webhook/deliveries?limit=5")
        body = resp.json()
        assert body["count"] == 1
        row = body["data"][0]
        assert row["event"] == "alert"
        assert row["ok"] is False
        assert row["attempts"] == 3
        assert row["symbol"] == "PEPEUSDT"
        assert isinstance(row["timestamp"], str)

    def test_test_send_logs_delivery(self, v29_client):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        ui_routes.set_webhook(WebhookDispatcher(
            WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler),
        ))
        resp = v29_client.post("/dashboard/api/webhook/test")
        body = resp.json()
        assert body["status"] == "success"
        assert body["sent"] is True
        assert body["status_code"] == 200
        assert body["attempts"] == 1
        # delivery test dicatat ke DB
        db = v29_client._v29_mock_db
        db.log_webhook_delivery.assert_awaited_once()
        kwargs = db.log_webhook_delivery.await_args.kwargs
        assert kwargs["event"] == "test"
        assert kwargs["ok"] is True

    def test_deliveries_memory_fallback(self, v29_client):
        db = v29_client._v29_mock_db
        db.get_webhook_deliveries = AsyncMock(side_effect=RuntimeError("db down"))
        ui_routes.set_webhook(WebhookDispatcher(WEBHOOK_FULL_URL))
        # isi last_result secara langsung (tanpa network)
        disp = ui_routes.get_webhook()
        disp.last_result = {"ok": False, "status_code": None,
                            "reason": "timeout", "attempts": 2,
                            "duration_ms": 99}
        resp = v29_client.get("/dashboard/api/webhook/deliveries")
        body = resp.json()
        assert body["source"] == "memory"
        assert body["count"] == 1
        assert body["data"][0]["reason"] == "timeout"
        # URL tidak pernah bocor
        assert WEBHOOK_FULL_URL not in json.dumps(body)


# ====================================================================
# 4. History priority filter endpoint
# ====================================================================

class TestHistoryPriorityEndpoint:
    def test_priority_passed_to_db(self, v29_client):
        resp = v29_client.get(
            "/dashboard/api/alerts/history", params={"priority": "HIGH"}
        )
        body = resp.json()
        assert body["status"] == "success"
        assert body["filters"]["priority"] == "high"
        kwargs = v29_client._v29_mock_db.get_alert_history.await_args.kwargs
        assert kwargs["priority"] == "high"

    def test_priority_invalid_ignored(self, v29_client):
        resp = v29_client.get(
            "/dashboard/api/alerts/history", params={"priority": "URGENT"}
        )
        body = resp.json()
        assert body["filters"]["priority"] is None
        kwargs = v29_client._v29_mock_db.get_alert_history.await_args.kwargs
        assert kwargs["priority"] is None

    def test_combined_filters(self, v29_client):
        resp = v29_client.get("/dashboard/api/alerts/history", params={
            "symbol": "dogeusdt", "hours": 24, "priority": "low",
        })
        body = resp.json()
        assert body["filters"] == {
            "symbol": "DOGEUSDT", "hours": 24, "priority": "low",
        }


# ====================================================================
# 5. Settings export/import
# ====================================================================

class TestSettingsExport:
    def test_export_shape_and_headers(self, v29_client):
        resp = v29_client.get("/dashboard/api/settings/export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "zcapital_settings_" in resp.headers.get("content-disposition", "")
        payload = json.loads(resp.text)
        assert payload["kind"] == "zcapital.settings_export"
        assert payload["version"] == 1
        assert "exported_at" in payload
        keys = {item["key"] for item in payload["settings"]}
        # int keys selalu ada; secret hanya bila pernah di-persist
        assert {
            "alert_history_retention_days", "dashboard_refresh_seconds",
            "anomaly_feed_limit",
        } <= keys

    def test_export_secret_never_plaintext(self, v29_client):
        # persist webhook_url terenkripsi via PUT biasa
        resp = v29_client.put("/dashboard/api/settings", json={
            "updates": {"webhook_url": WEBHOOK_FULL_URL},
        })
        assert resp.json()["results"]["webhook_url"]["ok"] is True
        db = v29_client._v29_mock_db
        stored_blob = db.set_app_setting.await_args.args[1]
        db.get_app_settings = AsyncMock(return_value={"webhook_url": stored_blob})
        raw = v29_client.get("/dashboard/api/settings/export").text
        assert WEBHOOK_FULL_URL not in raw
        payload = json.loads(raw)
        wh = [i for i in payload["settings"] if i["key"] == "webhook_url"]
        assert len(wh) == 1
        assert wh[0]["encoding"] == "enc:v1"
        assert wh[0]["value"].startswith("enc:v1:")
        # secret yang belum di-persist tidak ikut dalam export
        tg = [i for i in payload["settings"] if i["key"] == "telegram_bot_token"]
        assert tg == []

    def test_export_int_effective_value(self, v29_client):
        v29_client.put("/dashboard/api/settings", json={
            "updates": {"dashboard_refresh_seconds": "60"},
        })
        payload = json.loads(
            v29_client.get("/dashboard/api/settings/export").text
        )
        item = [i for i in payload["settings"]
                if i["key"] == "dashboard_refresh_seconds"][0]
        assert item["value"] == "60"


class TestSettingsImport:
    def test_import_ints_applied(self, v29_client):
        resp = v29_client.post("/dashboard/api/settings/import", json={
            "settings": [
                {"key": "dashboard_refresh_seconds", "value": "120", "encoding": None},
                {"key": "anomaly_feed_limit", "value": "50", "encoding": None},
            ],
        })
        body = resp.json()
        assert body["status"] == "success"
        assert body["summary"]["applied"] == 2
        assert body["summary"]["failed"] == 0
        assert body["results"]["dashboard_refresh_seconds"]["status"] == "applied"
        assert rs.get_int("dashboard_refresh_seconds", 0) == 120
        db = v29_client._v29_mock_db
        assert db.set_app_setting.await_count == 2

    def test_import_unknown_and_invalid(self, v29_client):
        resp = v29_client.post("/dashboard/api/settings/import", json={
            "settings": [
                {"key": "no_such_key", "value": "1", "encoding": None},
                {"key": "dashboard_refresh_seconds", "value": "abc", "encoding": None},
            ],
        })
        body = resp.json()
        assert body["results"]["no_such_key"]["status"] == "unknown_key"
        assert body["results"]["dashboard_refresh_seconds"]["status"] == "invalid_value"
        assert body["summary"]["applied"] == 0
        assert body["summary"]["failed"] == 2

    def test_import_rejects_plaintext_secret(self, v29_client):
        resp = v29_client.post("/dashboard/api/settings/import", json={
            "settings": [
                {"key": "telegram_bot_token", "value": "123:abc-plain", "encoding": None},
                {"key": "webhook_url", "value": WEBHOOK_FULL_URL, "encoding": None},
            ],
        })
        body = resp.json()
        assert body["results"]["telegram_bot_token"]["status"] == "rejected"
        assert body["results"]["webhook_url"]["status"] == "rejected"
        v29_client._v29_mock_db.set_app_setting.assert_not_awaited()

    def test_import_encrypted_blob_applied(self, v29_client):
        from app.runtime_settings import encrypt_secret, is_encrypted
        blob = encrypt_secret(WEBHOOK_FULL_URL)
        assert is_encrypted(blob)
        resp = v29_client.post("/dashboard/api/settings/import", json={
            "settings": [
                {"key": "webhook_url", "value": blob, "encoding": "enc:v1"},
            ],
        })
        body = resp.json()
        assert body["results"]["webhook_url"]["status"] == "secret_applied"
        assert body["summary"]["applied"] == 1
        # dispatcher runtime terpasang kembali dengan URL terdekripsi
        disp = ui_routes.get_webhook()
        assert disp is not None and disp.url == WEBHOOK_FULL_URL
        # tersimpan dalam bentuk terenkripsi (bukan plaintext)
        stored = v29_client._v29_mock_db.set_app_setting.await_args.args
        assert stored[1] == blob

    def test_import_tampered_blob_undecryptable(self, v29_client):
        resp = v29_client.post("/dashboard/api/settings/import", json={
            "settings": [
                {"key": "webhook_url", "value": "enc:v1:garbage-blob",
                 "encoding": "enc:v1"},
            ],
        })
        body = resp.json()
        assert body["results"]["webhook_url"]["status"] == "undecryptable"
        assert body["summary"]["applied"] == 0

    def test_import_roundtrip_export_restore(self, v29_client):
        # 1) set settings via PUT (webhook + int)
        v29_client.put("/dashboard/api/settings", json={
            "updates": {
                "dashboard_refresh_seconds": "90",
                "webhook_url": WEBHOOK_FULL_URL,
            },
        })
        # 2) export
        payload = json.loads(
            v29_client.get("/dashboard/api/settings/export").text
        )
        # 3) ubah lalu import ulang (simulasi restore)
        items = payload["settings"]
        for item in items:
            if item["key"] == "dashboard_refresh_seconds":
                item["value"] = "45"
        resp = v29_client.post(
            "/dashboard/api/settings/import", json={"settings": items}
        )
        body = resp.json()
        assert body["summary"]["applied"] >= 2
        assert rs.get_int("dashboard_refresh_seconds", 0) == 45
        assert ui_routes.get_webhook().url == WEBHOOK_FULL_URL

    def test_import_empty_settings_422(self, v29_client):
        resp = v29_client.post(
            "/dashboard/api/settings/import", json={"settings": []}
        )
        assert resp.status_code == 422


# ====================================================================
# 6. Guard HTML v2.9
# ====================================================================

class TestDashboardHtmlV29:
    @staticmethod
    def _html() -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent
                / "app" / "ui" / "templates" / "dashboard.html").read_text()

    def test_delivery_log_elements(self):
        html = self._html()
        for el_id in ("wh-delivery", "wh-del-head", "wh-del-list",
                      "wh-del-count"):
            assert f'id="{el_id}"' in html

    def test_history_search_and_priority_elements(self):
        html = self._html()
        for el_id in ("history-search", "history-search-clear",
                      "history-priority", "hist-search-wrap"):
            assert f'id="{el_id}"' in html

    def test_settings_export_import_elements(self):
        html = self._html()
        for el_id in ("settings-export-btn", "settings-import-btn",
                      "settings-import-modal", "settings-import-textarea",
                      "settings-import-submit-btn"):
            assert f'id="{el_id}"' in html

    def test_wiring_v29(self):
        html = self._html()
        for fn in ("loadWebhookDeliveries", "toggleDeliveryLog",
                   "submitSettingsImport", "applyHistoryTextFilter",
                   "historyItemMatchesSearch"):
            assert fn in html
        assert "history-search-clear" in html
        assert "loadWebhookDeliveries(); // v2.9" in html

    def test_i18n_settings_import_keys(self):
        html = self._html()
        for key in ("settings.import.title", "settings.import.sub",
                    "settings.import.run"):
            assert key in html

    def test_footer_version_bumped(self):
        html = self._html()
        assert "Crypto Oracle AI v2." in html  # v2.10+ allowed

    def test_app_version_bumped(self):
        from app.main import app as fastapi_app
        parts = fastapi_app.version.split(".")
        assert len(parts) == 3 and all(p.isdigit() for p in parts)
        assert tuple(int(p) for p in parts) >= (2, 9, 0)

    def test_hidden_display_none_rules_valid(self):
        """Elemen yang di-toggle hidden dan ber-display flex wajib punya
        rule author [hidden] (kelas bug ronde-9)."""
        html = self._html()
        for sel in (".history-item" + HIDDEN_SEL,
                    ".bulk-bar" + HIDDEN_SEL,
                    ".select-all-wrap" + HIDDEN_SEL,
                    ".wh-del-list" + HIDDEN_SEL):
            assert sel in html

    def test_no_corrupted_hidden_selectors(self):
        html = self._html()
        corrupt = "idden]"
        for line in html.splitlines():
            if corrupt in line:
                assert HIDDEN_SEL in line or '"hidden"' in line or \
                    "'hidden'" in line or "hidden " in line, \
                    f"possible corrupted selector: {line.strip()!r}"

    def test_no_invalid_unicode_escapes(self):
        """Semua escape \\uXXXX harus 4 hex valid - escape seperti
        \\dd25 (korupsi tooling ronde-8) tampil literal di UI."""
        import re
        html = self._html()
        bad = re.findall(r"\\u[0-9a-fA-F]{0,3}(?![0-9a-fA-F])", html)
        assert bad == [], f"invalid unicode escapes found: {set(bad)}"
        bad2 = re.findall(r"\\[dD][0-9a-fA-F]{2,4}", html)
        assert bad2 == [], f"broken unicode escapes found: {set(bad2)}"


# ====================================================================
# 7. Pipeline: alert -> webhook dispatch -> delivery log
# ====================================================================

class TestPipelineWebhookLogging:
    @pytest.mark.asyncio
    async def test_broadcast_alert_logs_delivery(self, v29_client):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        ui_routes.set_webhook(WebhookDispatcher(
            WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler),
        ))
        app_inst = MagicMock()
        app_inst.db = v29_client._v29_mock_db

        from app.main import CryptoOracleApp
        alert = {
            "rule": "extreme_volume_spike",
            "priority": "high",
            "symbol": "PEPEUSDT",
            "channels": ["dashboard"],
            "timestamp": "2026-01-01T00:00:00+00:00",
            "data": {"volume_spike": 500},
        }
        await CryptoOracleApp._dispatch_webhook_and_log(
            app_inst, ui_routes.get_webhook(), alert
        )
        db = v29_client._v29_mock_db
        db.log_webhook_delivery.assert_awaited_once()
        kwargs = db.log_webhook_delivery.await_args.kwargs
        assert kwargs["event"] == "alert"
        assert kwargs["ok"] is True
        assert kwargs["rule"] == "extreme_volume_spike"
        assert kwargs["symbol"] == "PEPEUSDT"

    @pytest.mark.asyncio
    async def test_retention_prunes_webhook_deliveries(self, v29_client):
        app_inst = MagicMock()
        app_inst.db = v29_client._v29_mock_db
        app_inst.settings.alert_history_retention_days = 7

        from app import runtime_settings
        from app.main import CryptoOracleApp
        runtime_settings._cache.clear()
        deleted = await CryptoOracleApp._prune_alert_history_once(app_inst)
        assert deleted == 0
        v29_client._v29_mock_db.prune_webhook_deliveries.assert_awaited_once_with(7)
