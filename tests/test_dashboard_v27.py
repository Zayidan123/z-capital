"""
Tests untuk fitur Dashboard v2.7:
- Audit sparkline per-rule: DB get_alert_rule_stats + endpoint
  GET /api/alerts/rule-stats (slot jam kosong diisi 0, clamp 1..168,
  total/last_fired/sort)
- Export rules JSON: GET /api/alerts/rules/export (attachment JSON,
  payload aman tanpa lambda)
- Import rules JSON: POST /api/alerts/rules/import (status per-item,
  batch tetap sukses walau ada item unknown / non-editable / invalid)
- Guard HTML v2.7: elemen command palette, import modal, i18n,
  selector atribut hidden dalam bentuk VALID (bukan korup)
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app.ui import routes as ui_routes
from app.ui.rate_limit import reset_all_limiters

# Selector atribut valid dibangun via konkatenasi agar aman dari
# mangling tooling (pelajaran bug ronde-7: "[h" bisa hilang saat tulis).
HIDDEN_SEL = "[" + "hidden]"


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
def v27_client():
    """TestClient + mock DB global untuk endpoint v2.7."""
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

        from app.main import app
        with TestClient(app) as test_client:
            ui_routes.set_notifier(None)
            test_client._v27_mock_db = mock_global_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()


# ====================================================================
# 1. Database layer: get_alert_rule_stats
# ====================================================================

class TestDatabaseRuleStats:
    @pytest.mark.asyncio
    async def test_sql_groups_by_rule_with_window(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        result = await db.get_alert_rule_stats(hours=24)
        assert result == []
        sql, params = conn.fetch.await_args.args
        assert "GROUP BY rule" in sql
        assert "make_interval(hours => $1)" in sql
        assert params == 24

    @pytest.mark.asyncio
    async def test_clamp_low_and_high(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_rule_stats(hours=0)
        assert conn.fetch.await_args.args[1] == 1

        await db.get_alert_rule_stats(hours=5000)
        assert conn.fetch.await_args.args[1] == 720

    @pytest.mark.asyncio
    async def test_rows_serialized_as_dicts(self):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {"rule": "extreme_volume_spike", "hour": now - timedelta(hours=2),
             "count": 3, "severity": 2},
        ])
        db = _make_db_with_conn(conn)

        rows = await db.get_alert_rule_stats(hours=24)
        assert rows[0]["rule"] == "extreme_volume_spike"
        assert rows[0]["count"] == 3


# ====================================================================
# 2. Endpoint GET /api/alerts/rule-stats
# ====================================================================

class TestRuleStatsEndpoint:
    def test_sparse_rows_filled_into_full_buckets(self, v27_client):
        db = v27_client._v27_mock_db
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        db.get_alert_rule_stats = AsyncMock(return_value=[
            {"rule": "extreme_volume_spike", "hour": now - timedelta(hours=5),
             "count": 2, "severity": 2},
            {"rule": "extreme_volume_spike", "hour": now - timedelta(hours=1),
             "count": 1, "severity": 2},
        ])

        res = v27_client.get("/dashboard/api/alerts/rule-stats?hours=24")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["window_hours"] == 24
        assert body["count"] == 1

        entry = body["data"][0]
        assert entry["rule"] == "extreme_volume_spike"
        assert entry["total"] == 3
        assert len(entry["buckets"]) == 24  # slot jam kosong diisi
        # bucket terbaru (index terakhir) = jam "now"
        assert entry["buckets"][-1]["count"] == 0
        assert entry["buckets"][-2]["count"] == 1   # now - 1h
        assert entry["buckets"][-2]["hour"] == (now - timedelta(hours=1)).isoformat()
        assert entry["buckets"][-6]["count"] == 2   # now - 5h
        assert entry["last_fired"] == (now - timedelta(hours=1)).isoformat()

    def test_sorted_by_total_desc(self, v27_client):
        db = v27_client._v27_mock_db
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        db.get_alert_rule_stats = AsyncMock(return_value=[
            {"rule": "aaa_rule", "hour": now, "count": 1, "severity": 1},
            {"rule": "bbb_rule", "hour": now, "count": 7, "severity": 2},
        ])
        body = v27_client.get("/dashboard/api/alerts/rule-stats").json()
        totals = [d["total"] for d in body["data"]]
        assert totals == sorted(totals, reverse=True)
        assert body["data"][0]["rule"] == "bbb_rule"

    def test_clamp_window(self, v27_client):
        db = v27_client._v27_mock_db
        db.get_alert_rule_stats = AsyncMock(return_value=[])

        body = v27_client.get("/dashboard/api/alerts/rule-stats?hours=999").json()
        assert body["window_hours"] == 168
        assert db.get_alert_rule_stats.await_args.kwargs["hours"] == 168

        body = v27_client.get("/dashboard/api/alerts/rule-stats?hours=0").json()
        assert body["window_hours"] == 1

    def test_db_error_structured(self, v27_client):
        db = v27_client._v27_mock_db
        db.get_alert_rule_stats = AsyncMock(side_effect=RuntimeError("db down"))
        body = v27_client.get("/dashboard/api/alerts/rule-stats").json()
        assert body["status"] == "error"
        assert "db down" in body["message"]

    def test_empty_history_no_rows(self, v27_client):
        db = v27_client._v27_mock_db
        db.get_alert_rule_stats = AsyncMock(return_value=[])
        body = v27_client.get("/dashboard/api/alerts/rule-stats").json()
        assert body["status"] == "success"
        assert body["count"] == 0
        assert body["data"] == []


# ====================================================================
# 3. Endpoint GET /api/alerts/rules/export
# ====================================================================

class TestRulesExport:
    def test_export_attachment_shape(self, v27_client):
        res = v27_client.get("/dashboard/api/alerts/rules/export")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
        assert "attachment" in res.headers.get("content-disposition", "")
        assert "alert_rules_" in res.headers.get("content-disposition", "")

        payload = json.loads(res.text)
        assert payload["kind"] == "zcapital.alert_rules"
        assert payload["version"] == "2.7"
        assert "exported_at" in payload
        assert payload["count"] == len(payload["rules"])
        assert payload["count"] >= 1

        for rule in payload["rules"]:
            # lambda condition tidak boleh bocor ke JSON
            assert "condition" not in rule
            assert {"name", "priority", "editable"} <= set(rule.keys())

    def test_export_reflects_runtime_threshold(self, v27_client):
        v27_client.put("/dashboard/api/alerts/rules/extreme_volume_spike",
                       json={"threshold": 777.0})
        payload = json.loads(
            v27_client.get("/dashboard/api/alerts/rules/export").text
        )
        by_name = {r["name"]: r for r in payload["rules"]}
        assert by_name["extreme_volume_spike"]["threshold"] == 777.0

    def test_export_error_structured(self, v27_client):
        with patch.object(ui_routes, "get_alert_system_async",
                          side_effect=RuntimeError("boom")):
            res = v27_client.get("/dashboard/api/alerts/rules/export")
            assert res.status_code == 200  # error dibungkus JSON, bukan 500
            body = res.json()
            assert body["status"] == "error"


# ====================================================================
# 4. Endpoint POST /api/alerts/rules/import
# ====================================================================

class TestRulesImport:
    def test_bulk_import_updates_and_persists(self, v27_client):
        db = v27_client._v27_mock_db
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={
            "rules": [
                {"name": "extreme_volume_spike", "threshold": 900.0},
                {"name": "confirmed_signal", "threshold": 0.55},
            ]
        })
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["received"] == 2
        assert body["updated"] == 2
        statuses = {r["name"]: r["status"] for r in body["results"]}
        assert statuses == {
            "extreme_volume_spike": "updated",
            "confirmed_signal": "updated",
        }
        # persist dipanggil per rule
        assert db.upsert_alert_rule_threshold.await_count == 2

        # engine state benar-benar berubah
        rules = v27_client.get("/dashboard/api/alerts/rules").json()["data"]
        by_name = {r["name"]: r for r in rules}
        assert by_name["extreme_volume_spike"]["threshold"] == 900.0
        assert by_name["confirmed_signal"]["threshold"] == 0.55

    def test_mixed_statuses_partial_success(self, v27_client):
        db = v27_client._v27_mock_db
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={
            "rules": [
                {"name": "extreme_volume_spike", "threshold": 650.0},
                {"name": "no_such_rule", "threshold": 10.0},
                {"name": "smart_money_detected", "threshold": 5.0},  # non-editable
                {"name": "confirmed_signal", "threshold": -3.0},      # invalid
            ]
        })
        body = res.json()
        assert body["status"] == "success"
        assert body["received"] == 4
        assert body["updated"] == 1
        statuses = {r["name"]: r["status"] for r in body["results"]}
        assert statuses["extreme_volume_spike"] == "updated"
        assert statuses["no_such_rule"] == "unknown"
        assert statuses["smart_money_detected"] == "not_editable"
        assert statuses["confirmed_signal"] == "invalid_threshold"
        # hanya rule valid yang persist
        assert db.upsert_alert_rule_threshold.await_count == 1

    def test_nan_and_inf_rejected_per_item(self, v27_client):
        # NaN/Infinity tidak bisa lewat json client standar; kirim raw body
        # (json.loads python menerima NaN/Infinity, pydantic float pun)
        raw = '{"rules": [{"name": "extreme_volume_spike", "threshold": NaN},'
        raw += ' {"name": "confirmed_signal", "threshold": Infinity}]}'
        res = v27_client.post(
            "/dashboard/api/alerts/rules/import",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        body = res.json()
        assert body["updated"] == 0
        assert all(r["status"] == "invalid_threshold" for r in body["results"])

    def test_whitespace_name_treated_invalid(self, v27_client):
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={
            "rules": [{"name": "   ", "threshold": 10.0}]
        })
        body = res.json()
        assert body["updated"] == 0
        assert body["results"][0]["status"] == "invalid_threshold"

    def test_missing_rules_field_422(self, v27_client):
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={})
        assert res.status_code == 422

    def test_empty_rules_list_422(self, v27_client):
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={"rules": []})
        assert res.status_code == 422

    def test_name_too_long_422(self, v27_client):
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={
            "rules": [{"name": "x" * 200, "threshold": 10.0}]
        })
        assert res.status_code == 422

    def test_roundtrip_export_then_import(self, v27_client):
        # export -> ubah nilai -> import kembali -> threshold ter-restore
        original = json.loads(
            v27_client.get("/dashboard/api/alerts/rules/export").text
        )
        v27_client.put("/dashboard/api/alerts/rules/extreme_volume_spike",
                       json={"threshold": 12345.0})
        reimport = {
            "rules": [
                {"name": r["name"], "threshold": r["threshold"]}
                for r in original["rules"] if r["editable"]
            ]
        }
        body = v27_client.post("/dashboard/api/alerts/rules/import",
                               json=reimport).json()
        assert body["updated"] >= 1
        rules = v27_client.get("/dashboard/api/alerts/rules").json()["data"]
        by_name = {r["name"]: r for r in rules}
        assert by_name["extreme_volume_spike"]["threshold"] == 500.0

    def test_persist_failure_still_updates_memory(self, v27_client):
        db = v27_client._v27_mock_db
        db.upsert_alert_rule_threshold = AsyncMock(
            side_effect=RuntimeError("db down")
        )
        res = v27_client.post("/dashboard/api/alerts/rules/import", json={
            "rules": [{"name": "extreme_volume_spike", "threshold": 400.0}]
        })
        body = res.json()
        assert body["status"] == "success"
        result = body["results"][0]
        assert result["status"] == "updated"
        assert result["persisted"] is False
        # state in-memory tetap berubah
        rules = v27_client.get("/dashboard/api/alerts/rules").json()["data"]
        by_name = {r["name"]: r for r in rules}
        assert by_name["extreme_volume_spike"]["threshold"] == 400.0


# ====================================================================
# 5. Guard HTML v2.7
# ====================================================================

def _html() -> str:
    from pathlib import Path
    tpl = (Path(__file__).resolve().parent.parent / "app" / "ui" /
           "templates" / "dashboard.html")
    return tpl.read_text(encoding="utf-8")


class TestDashboardHtmlV27:
    def test_new_elements_present(self):
        html = _html()
        for frag in (
            'id="palette-backdrop"',
            'id="palette-input"',
            'id="palette-list"',
            'id="import-modal"',
            'id="import-textarea"',
            'id="import-file"',
            'id="import-submit-btn"',
            'id="rules-export-btn"',
            'id="rules-import-btn"',
            'id="lang-btn"',
        ):
            assert frag in html, f"missing element: {frag}"

    def test_i18n_attributes_wired(self):
        html = _html()
        assert html.count("data-i18n=") >= 13
        # pasangan key di atribut harus ada di kamus I18N JS
        import re
        keys = set(re.findall(r'data-i18n="([^"]+)"', html))
        assert {"title.pulse", "title.rules", "title.heatmap",
                "import.run", "rules.hint"} <= keys

    def test_rule_audit_rendered_via_stats(self):
        html = _html()
        assert "renderRuleAudit" in html
        assert "rule-stats?hours=24" in html
        assert "rule-audit" in html

    def test_hidden_rules_still_valid(self):
        html = _html()
        for sel in (".error-banner", ".modal-backdrop", ".offline-banner"):
            assert f"{sel}{HIDDEN_SEL} {{ display: none; }}" in html
        import re
        residual = html.replace(HIDDEN_SEL, "@@OK@@")
        assert not re.findall(r"[a-z-]+idden\]", residual)

    def test_footer_version_bumped(self):
        html = _html()
        assert "Crypto Oracle AI v2.7" in html

    def test_palette_shortcut_registered(self):
        html = _html()
        assert "toLowerCase() === 'k'" in html
        assert "k === 'l'" in html


# ====================================================================
# 6. Versi aplikasi
# ====================================================================

class TestVersionV27:
    def test_app_version_bumped(self):
        from app.main import app as fastapi_app
        assert fastapi_app.version == "2.7.0"
