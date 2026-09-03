"""
Tests untuk fitur Dashboard v2.8:
- WebhookDispatcher (app/notifier.py): payload, masking URL, dispatch
  sukses/gagal/timeout (httpx.MockTransport), test_send
- Webhook channel endpoints: GET /api/webhook/status,
  POST /api/webhook/test (sent=False bila not configured)
- Runtime settings: spec webhook_url, PUT validasi format (http/https +
  host), persist terenkripsi, GET /api/settings masked (hanya
  scheme://host, path TIDAK pernah bocor)
- Bulk edit rules: POST /api/alerts/rules/bulk (status per-item,
  NaN/Inf/negatif ditolak, batas 1..50 nama)
- Guard HTML v2.8: bulk bar, select-all, checkbox rule, webhook section,
  sparkline tooltip, selector atribut hidden tetap valid
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app.notifier import WebhookDispatcher, mask_webhook_url
from app import runtime_settings as rs
from app.ui import routes as ui_routes
from app.ui.rate_limit import reset_all_limiters

# Selector atribut valid dibangun via konkatenasi agar aman dari
# mangling tooling saat transfer output (pelajaran ronde-7).
HIDDEN_SEL = "[" + "hidden]"

WEBHOOK_FULL_URL = "https://hooks.example.com/TOKEN123/abc?secret=1"
WEBHOOK_MASKED = "https://hooks.example.com"


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
def v28_client():
    """TestClient + mock DB global untuk endpoint v2.8."""
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
        mock_global_db.get_app_settings = AsyncMock(return_value={})
        mock_global_db.set_app_setting = AsyncMock()
        mock_global_db._initialized = True

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        reset_all_limiters()
        ui_routes.reset_engines()
        rs._cache.clear()

        from app.main import app
        with TestClient(app) as test_client:
            ui_routes.set_notifier(None)
            test_client._v28_mock_db = mock_global_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()
        rs._cache.clear()


def _mock_transport(status_code: int = 200) -> httpx.MockTransport:
    """MockTransport yang mencatat request dan membalas status tetap."""

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        return httpx.Response(
            status_code,
            json={"received": bool(request.content)},
            headers={"content-type": "application/json"},
        )

    return httpx.MockTransport(handler)


# ====================================================================
# 1. Unit: mask_webhook_url + WebhookDispatcher
# ====================================================================

class TestMaskWebhookUrl:
    def test_masks_path_and_query(self):
        masked = mask_webhook_url(WEBHOOK_FULL_URL)
        assert masked == WEBHOOK_MASKED
        assert "TOKEN123" not in masked
        assert "secret" not in masked

    def test_bogus_returns_none(self):
        assert mask_webhook_url("not a url") is None
        assert mask_webhook_url("") is None
        assert mask_webhook_url(None) is None

    def test_plain_host_unchanged_shape(self):
        assert mask_webhook_url("http://10.0.0.5:9000/hook") == "http://10.0.0.5:9000"


class TestWebhookDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_success_2xx(self):
        d = WebhookDispatcher(WEBHOOK_FULL_URL, transport=_mock_transport(200))
        result = await d.dispatch()
        assert result["ok"] is True
        assert result["status_code"] == 200
        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_dispatch_non_2xx_is_failure(self):
        d = WebhookDispatcher(WEBHOOK_FULL_URL, transport=_mock_transport(500))
        result = await d.dispatch()
        assert result["ok"] is False
        assert result["reason"] == "http_500"
        assert d.last_result == result

    @pytest.mark.asyncio
    async def test_dispatch_never_raises_on_connection_error(self):
        d = WebhookDispatcher("http://127.0.0.1:1/nowhere")
        result = await d.dispatch()
        assert result["ok"] is False
        assert result["reason"] in ("error", "timeout")

    @pytest.mark.asyncio
    async def test_dispatch_not_configured(self):
        d = WebhookDispatcher("")
        result = await d.dispatch()
        # v2.9: hasil kini mencatat attempts + duration_ms
        assert result["ok"] is False
        assert result["status_code"] is None
        assert result["reason"] == "not_configured"
        assert result["attempts"] == 0
        assert result["duration_ms"] == 0

    @pytest.mark.asyncio
    async def test_test_payload_shape(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content.decode())
            captured["header"] = request.headers.get("x-zcapital-event")
            return httpx.Response(200)

        d = WebhookDispatcher(WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler))
        await d.test_send()
        body = captured["json"]
        assert body["source"] == "z-capital"
        assert body["type"] == "alert.test"
        assert "timestamp" in body
        assert captured["header"] == "test"

    @pytest.mark.asyncio
    async def test_alert_payload_shape(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content.decode())
            captured["header"] = request.headers.get("x-zcapital-event")
            return httpx.Response(202)

        d = WebhookDispatcher(WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler))
        result = await d.dispatch(alert={
            "rule": "extreme_volume_spike",
            "priority": "HIGH",
            "symbol": "PEPEUSDT",
            "channels": ["telegram", "log"],
            "timestamp": "2026-09-03T12:00:00+00:00",
            "data": {"volume_spike": 900},
        })
        assert result["ok"] is True
        assert result["status_code"] == 202
        body = captured["json"]
        assert body["type"] == "alert.triggered"
        assert body["alert"]["rule"] == "extreme_volume_spike"
        assert body["alert"]["data"]["volume_spike"] == 900
        assert captured["header"] == "alert"

    def test_get_status_never_leaks_url(self):
        d = WebhookDispatcher(WEBHOOK_FULL_URL)
        status = d.get_status()
        assert status["configured"] is True
        assert status["url_masked"] == WEBHOOK_MASKED
        assert "TOKEN123" not in json.dumps(status)


# ====================================================================
# 2. Runtime settings: spec webhook_url
# ====================================================================

class TestWebhookSettingsSpec:
    def test_spec_registered_as_secret(self):
        spec = rs.SPECS_BY_KEY["webhook_url"]
        assert spec["type"] == "secret"
        assert spec["default"] is None

    def test_payload_masks_url_never_leaks_path(self):
        stored = rs.encrypt_secret(WEBHOOK_FULL_URL)
        payload = rs.build_settings_payload({"webhook_url": stored}, {})
        item = next(
            i for i in payload["settings"] if i["key"] == "webhook_url"
        )
        assert item["secret"] is True
        assert item["value"] is None
        assert item["masked"] == WEBHOOK_MASKED
        assert "TOKEN123" not in json.dumps(payload)


# ====================================================================
# 3. Endpoint: PUT /api/settings + GET status/test webhook
# ====================================================================

class TestWebhookEndpoints:
    def test_status_not_configured(self, v28_client):
        res = v28_client.get("/dashboard/api/webhook/status")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["data"]["configured"] is False
        assert body["data"]["url_masked"] is None

    def test_test_not_configured(self, v28_client):
        res = v28_client.post("/dashboard/api/webhook/test")
        assert res.status_code == 200
        body = res.json()
        assert body["sent"] is False
        assert body["reason"] == "not_configured"

    def test_test_delivered_via_injected_transport(self, v28_client):
        ui_routes.set_webhook(
            WebhookDispatcher(WEBHOOK_FULL_URL, transport=_mock_transport(200))
        )
        res = v28_client.post("/dashboard/api/webhook/test")
        body = res.json()
        assert body["status"] == "success"
        assert body["sent"] is True
        assert body["status_code"] == 200
        # URL tidak pernah muncul di response
        assert "TOKEN123" not in json.dumps(body)

    def test_test_failure_reported_as_result(self, v28_client):
        ui_routes.set_webhook(
            WebhookDispatcher(WEBHOOK_FULL_URL, transport=_mock_transport(503))
        )
        res = v28_client.post("/dashboard/api/webhook/test")
        body = res.json()
        assert body["sent"] is False
        assert body["reason"] == "http_503"

    def test_put_settings_webhook_valid_applies_and_persists(self, v28_client):
        res = v28_client.put(
            "/dashboard/api/settings",
            json={"updates": {"webhook_url": WEBHOOK_FULL_URL}},
        )
        assert res.status_code == 200
        result = res.json()["results"]["webhook_url"]
        assert result["ok"] is True
        assert result["applied"] is True
        assert result["persisted"] is True
        assert result["masked"] == WEBHOOK_MASKED

        # dispatcher runtime terpasang dengan URL penuh
        dispatcher = ui_routes.get_webhook()
        assert dispatcher is not None
        assert dispatcher.url == WEBHOOK_FULL_URL
        # persist terenkripsi (bukan plaintext)
        db = v28_client._v28_mock_db
        key, stored = db.set_app_setting.await_args.args
        assert key == "webhook_url"
        assert rs.is_encrypted(stored)
        assert rs.decrypt_secret(stored) == WEBHOOK_FULL_URL
        # cache override ikut ter-update
        assert rs._cache["webhook_url"] == stored

    def test_put_settings_webhook_invalid_scheme_rejected(self, v28_client):
        res = v28_client.put(
            "/dashboard/api/settings",
            json={"updates": {"webhook_url": "ftp://example.com/hook"}},
        )
        result = res.json()["results"]["webhook_url"]
        assert result["ok"] is False
        assert "http" in result["warning"]
        assert ui_routes.get_webhook() is None

    def test_put_settings_webhook_no_host_rejected(self, v28_client):
        res = v28_client.put(
            "/dashboard/api/settings",
            json={"updates": {"webhook_url": "https://"}},
        )
        result = res.json()["results"]["webhook_url"]
        assert result["ok"] is False
        assert ui_routes.get_webhook() is None

    def test_get_settings_masks_webhook_url(self, v28_client):
        stored = rs.encrypt_secret(WEBHOOK_FULL_URL)
        rs._cache["webhook_url"] = stored
        with patch.object(
            ui_routes, "load_overrides",
            AsyncMock(return_value={"webhook_url": stored}),
        ):
            res = v28_client.get("/dashboard/api/settings")
        assert res.status_code == 200
        items = {
            i["key"]: i for i in res.json()["data"]["settings"]
        }
        item = items["webhook_url"]
        assert item["set"] is True
        assert item["value"] is None
        assert item["masked"] == WEBHOOK_MASKED
        assert "TOKEN123" not in res.text


# ====================================================================
# 4. Endpoint: POST /api/alerts/rules/bulk
# ====================================================================

class TestBulkRuleUpdate:
    def test_bulk_two_rules_updated(self, v28_client):
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": ["extreme_volume_spike", "confirmed_signal"],
                  "threshold": 42.5},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["received"] == 2
        assert body["updated"] == 2
        statuses = {r["name"]: r for r in body["results"]}
        for name in ("extreme_volume_spike", "confirmed_signal"):
            assert statuses[name]["status"] == "updated"
            assert statuses[name]["threshold"] == 42.5
            assert statuses[name]["persisted"] is True

    def test_bulk_mixed_statuses_partial_success(self, v28_client):
        # smart_money_detected = non-editable (condition lambda)
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": ["extreme_volume_spike", "smart_money_detected",
                           "no_such_rule"],
                  "threshold": 10},
        )
        body = res.json()
        assert body["updated"] == 1
        statuses = {r["name"]: r["status"] for r in body["results"]}
        assert statuses["extreme_volume_spike"] == "updated"
        assert statuses["smart_money_detected"] == "not_editable"
        assert statuses["no_such_rule"] == "unknown"

    def test_bulk_nan_threshold_rejected_400(self, v28_client):
        raw = json.dumps({"names": ["extreme_volume_spike"], "threshold": float("nan")})
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 400

    def test_bulk_infinity_threshold_rejected_400(self, v28_client):
        raw = json.dumps(
            {"names": ["extreme_volume_spike"], "threshold": float("inf")}
        )
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 400

    def test_bulk_negative_threshold_rejected_400(self, v28_client):
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": ["extreme_volume_spike"], "threshold": -1},
        )
        assert res.status_code == 400

    def test_bulk_empty_names_422(self, v28_client):
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": [], "threshold": 1},
        )
        assert res.status_code == 422

    def test_bulk_more_than_50_names_422(self, v28_client):
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": [f"rule{i}" for i in range(51)], "threshold": 1},
        )
        assert res.status_code == 422

    def test_bulk_whitespace_name_marked_invalid(self, v28_client):
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": ["   "], "threshold": 1},
        )
        body = res.json()
        assert body["updated"] == 0
        assert body["results"][0]["status"] == "invalid_name"

    def test_bulk_threshold_not_persisted_when_db_fails(self, v28_client):
        db = v28_client._v28_mock_db
        db.upsert_alert_rule_threshold = AsyncMock(side_effect=RuntimeError("db down"))
        res = v28_client.post(
            "/dashboard/api/alerts/rules/bulk",
            json={"names": ["extreme_volume_spike"], "threshold": 77},
        )
        body = res.json()
        assert body["updated"] == 1
        assert body["results"][0]["persisted"] is False
        # threshold runtime tetap berubah meski persist gagal
        rules = {r["name"]: r for r in v28_client.get(
            "/dashboard/api/alerts/rules").json()["data"]}
        assert rules["extreme_volume_spike"]["threshold"] == 77


# ====================================================================
# 6. Pipeline: alert ter-trigger -> callback -> webhook dispatch (v2.8)
# ====================================================================

class TestAlertToWebhookPipeline:
    @pytest.mark.asyncio
    async def test_broadcast_alert_dispatches_webhook(self):
        """_broadcast_alert harus mengirim alert ke webhook terpasang."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content.decode())
            captured["header"] = request.headers.get("x-zcapital-event")
            return httpx.Response(200)

        ui_routes.set_webhook(
            WebhookDispatcher(WEBHOOK_FULL_URL, transport=httpx.MockTransport(handler))
        )
        try:
            from app.main import CryptoOracleApp

            app_orch = CryptoOracleApp()
            alert = {
                "rule": "extreme_volume_spike",
                "priority": "HIGH",
                "symbol": "PEPEUSDT",
                "channels": ["telegram", "log"],
                "timestamp": "2026-09-03T12:00:00+00:00",
                "data": {"volume_spike": 999, "confidence_score": 0.9},
            }
            await app_orch._broadcast_alert(alert)
            # dispatch berjalan sebagai background task - beri kesempatan jalan
            for _ in range(40):
                if "json" in captured:
                    break
                await asyncio.sleep(0.05)
            body = captured.get("json", {})
            assert body.get("type") == "alert.triggered"
            assert body.get("alert", {}).get("rule") == "extreme_volume_spike"
            assert body.get("alert", {}).get("symbol") == "PEPEUSDT"
            assert captured.get("header") == "alert"
        finally:
            ui_routes.set_webhook(None)

    @pytest.mark.asyncio
    async def test_broadcast_alert_without_webhook_is_noop(self):
        """Bila webhook tidak dipasang, broadcast tetap sukses tanpa error."""
        ui_routes.set_webhook(None)
        from app.main import CryptoOracleApp

        app_orch = CryptoOracleApp()
        # Tidak boleh raise walau tanpa webhook & tanpa koneksi WS aktif
        await app_orch._broadcast_alert({
            "rule": "medium_spike", "priority": "MEDIUM", "symbol": "DOGEUSDT",
            "channels": [], "timestamp": None, "data": {},
        })


# ====================================================================
# 7. Guard HTML v2.8
# ====================================================================

class TestDashboardHtmlV28:
    def _html(self) -> str:
        from pathlib import Path
        tpl = Path(__file__).resolve().parents[1] / "app" / "ui" / "templates" / "dashboard.html"
        return tpl.read_text(encoding="utf-8")

    def test_bulk_bar_elements_present(self):
        html = self._html()
        assert 'id="bulk-bar"' in html
        assert 'id="bulk-count"' in html
        assert 'id="bulk-threshold"' in html
        assert 'id="bulk-apply-btn"' in html
        assert 'id="bulk-clear-btn"' in html
        assert 'id="select-all-wrap"' in html
        assert 'id="rule-select-all"' in html

    def test_bulk_js_wired(self):
        html = self._html()
        assert "applyBulkThreshold" in html
        assert "clearBulkSelection" in html
        assert "bulkSelected" in html
        assert "syncSelectAllState" in html
        assert "/api/alerts/rules/bulk" in html
        assert "data-check" in html

    def test_webhook_section_present(self):
        html = self._html()
        assert 'id="webhook-section"' in html
        assert 'id="wh-url-input"' in html
        assert 'id="wh-apply-btn"' in html
        assert 'id="wh-test-btn"' in html
        assert 'id="wh-url-value"' in html
        assert 'id="wh-last-value"' in html
        assert "/api/webhook/status" in html
        assert "/api/webhook/test" in html

    def test_webhook_js_functions(self):
        html = self._html()
        for fn in ("loadWebhookStatus", "applyWebhook", "testWebhook"):
            assert f"function {fn}" in html or f"async function {fn}" in html

    def test_sparkline_tooltip_elements(self):
        html = self._html()
        assert "spark-tip" in html
        assert "ensureSparkTip" in html
        assert 'class=\\"bar\\"' in html or 'class="bar"' in html
        # <title> native tidak lagi dipakai untuk bar sparkline
        assert "rect class=\"bar\"" in html

    def test_hidden_display_none_rules_valid(self):
        html = self._html()
        for sel in (".error-banner", ".modal-backdrop", ".offline-banner"):
            assert f"{sel}{HIDDEN_SEL} {{ display: none; }}" in html

    def test_flex_elements_have_author_hidden_rules(self):
        """Elemen dgn display:flex/inline-flex WAJIB punya rule [hidden]
        level author - tanpa itu, rule UA [hidden]{display:none} kalah
        dan elemen tetap tampil walau atribut hidden terpasang
        (regresi kelas v2.3, ditemukan QA visual v2.8)."""
        html = self._html()
        assert ".bulk-bar" + HIDDEN_SEL + " { display: none; }" in html
        assert ".select-all-wrap" + HIDDEN_SEL + " { display: none; }" in html

    def test_palette_has_webhook_and_bulk_actions(self):
        html = self._html()
        assert "Send webhook test payload" in html
        assert "Apply bulk threshold to selected rules" in html

    def test_i18n_webhook_key(self):
        html = self._html()
        assert "webhook.sub" in html

    def test_footer_version_bumped(self):
        html = self._html()
        assert "Crypto Oracle AI v2." in html

    def test_app_version_bumped(self):
        from app.main import app as fastapi_app
        parts = fastapi_app.version.split(".")
        assert len(parts) == 3 and all(p.isdigit() for p in parts)
        assert tuple(int(p) for p in parts) >= (2, 8, 0)
