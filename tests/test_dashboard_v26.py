"""
Tests untuk fitur Dashboard v2.6:
- Runtime settings: tabel app_settings, modul runtime_settings (enkripsi
  secret, validasi/clamp), endpoint GET/PUT /api/settings
- Telegram runtime reconfiguration (notifier.reconfigure + startup restore)
- Filter alert history (symbol/hours) untuk click-to-filter heat map
- Export heat map CSV + PWA manifest
- Retensi membaca override runtime (main.py loop)
- Browser notification + offline indicator = pure frontend (QA browser,
  bukan pytest) - di sini hanya test backend counterpart-nya.
"""
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database as app_database
from app.config import settings as app_settings
from app.notifier import TelegramNotifier
from app import runtime_settings as rs
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
def clean_rs_cache():
    """Pastikan cache runtime settings bersih sebelum & sesudah test."""
    rs._cache.clear()
    yield
    rs._cache.clear()


@pytest.fixture
def v26_client(clean_rs_cache):
    """TestClient + mock DB global untuk endpoint v2.6."""
    with patch("app.main.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("app.main.BinanceStreamer") as mock_streamer_cls, \
         patch("app.main.TelegramNotifier") as mock_notifier_cls, \
         patch("app.main.DeepDiveAnalyzer") as mock_analyzer_cls, \
         patch("app.database.db") as mock_global_db:

        mock_db = MagicMock()
        mock_db.disconnect = AsyncMock()
        mock_get_db.return_value = mock_db

        # v2.5/v2.6 methods pada global db (dipakai routes langsung)
        mock_global_db.get_alert_heatmap = AsyncMock(return_value=[])
        mock_global_db.get_alert_history_stats = AsyncMock(
            return_value={"total_alerts": 0, "oldest_alert": None}
        )
        mock_global_db.prune_alert_history = AsyncMock(return_value=0)
        mock_global_db._initialized = True
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
        mock_global_db.get_app_settings = AsyncMock(return_value={})
        mock_global_db.set_app_setting = AsyncMock()

        for mock_cls in (mock_streamer_cls, mock_notifier_cls, mock_analyzer_cls):
            instance = mock_cls.return_value
            instance.start = AsyncMock()
            instance.stop = AsyncMock()

        reset_all_limiters()
        ui_routes.reset_engines()

        from app.main import app
        with TestClient(app) as test_client:
            ui_routes.set_notifier(None)
            test_client._v26_mock_db = mock_global_db  # type: ignore[attr-defined]
            yield test_client

        reset_all_limiters()
        ui_routes.reset_engines()


# ====================================================================
# 1. Config: field dashboard_secret_salt
# ====================================================================

class TestConfigV26:
    def test_secret_salt_optional(self):
        assert getattr(app_settings, "dashboard_secret_salt", "missing") is None or \
            isinstance(app_settings.dashboard_secret_salt, str)


# ====================================================================
# 2. Database layer: app_settings + history filters
# ====================================================================

class TestDatabaseV26:
    @pytest.mark.asyncio
    async def test_get_app_settings_all(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {"key": "a", "value": "1"}, {"key": "b", "value": "2"},
        ])
        db = _make_db_with_conn(conn)

        result = await db.get_app_settings()
        assert result == {"a": "1", "b": "2"}
        sql = conn.fetch.await_args.args[0]
        assert "FROM app_settings" in sql
        assert "$1" not in sql  # tanpa filter

    @pytest.mark.asyncio
    async def test_get_app_settings_filtered(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"key": "a", "value": "1"}])
        db = _make_db_with_conn(conn)

        result = await db.get_app_settings(keys=["a", "zzz"])
        assert result == {"a": "1"}
        sql, params = conn.fetch.await_args.args
        assert "key = ANY($1)" in sql
        assert params == ["a", "zzz"]

    @pytest.mark.asyncio
    async def test_set_app_setting_upsert(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _make_db_with_conn(conn)

        await db.set_app_setting("k", "v")
        sql, *params = conn.execute.await_args.args
        assert "INSERT INTO app_settings" in sql
        assert "ON CONFLICT (key) DO UPDATE" in sql
        assert params[0] == "k" and params[1] == "v"

    @pytest.mark.asyncio
    async def test_delete_app_setting_deleted(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 1")
        db = _make_db_with_conn(conn)
        assert await db.delete_app_setting("k") is True

    @pytest.mark.asyncio
    async def test_delete_app_setting_missing(self):
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 0")
        db = _make_db_with_conn(conn)
        assert await db.delete_app_setting("k") is False

    @pytest.mark.asyncio
    async def test_history_filters_symbol_and_hours(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_history(limit=10, symbol="PEPEUSDT", hours=24)
        sql, *params = conn.fetch.await_args.args
        assert "WHERE" in sql
        assert "symbol = $1" in sql
        assert "make_interval(hours => $2)" in sql
        assert params[0] == "PEPEUSDT"
        assert params[1] == 24
        assert params[2] == 10  # limit selalu argumen terakhir

    @pytest.mark.asyncio
    async def test_history_no_filters_plain_sql(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_history(limit=5)
        sql, *params = conn.fetch.await_args.args
        assert "WHERE" not in sql
        assert params[0] == 5

    @pytest.mark.asyncio
    async def test_history_hours_only(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        db = _make_db_with_conn(conn)

        await db.get_alert_history(limit=5, hours=48)
        sql, *params = conn.fetch.await_args.args
        assert "symbol = " not in sql
        assert "make_interval(hours => $1)" in sql
        assert params[0] == 48
        assert params[1] == 5


# ====================================================================
# 3. Modul runtime_settings: enkripsi, validasi, cache
# ====================================================================

class TestRuntimeSettingsModule:
    def test_encrypt_decrypt_roundtrip(self):
        enc = rs.encrypt_secret("12345:ABC-def")
        assert enc.startswith("enc:v1:")
        assert "12345" not in enc  # bukan plaintext
        assert rs.decrypt_secret(enc) == "12345:ABC-def"

    def test_decrypt_invalid_returns_none(self):
        assert rs.decrypt_secret("not-encrypted") is None
        assert rs.decrypt_secret("enc:v1:garbage") is None
        assert rs.decrypt_secret("") is None

    def test_is_encrypted(self):
        assert rs.is_encrypted(rs.encrypt_secret("x")) is True
        assert rs.is_encrypted("plain") is False

    def test_validate_int_clamps(self):
        spec = {"type": "int", "min": 0, "max": 365}
        res = rs.validate_value(spec, "999")
        assert res["ok"] and res["value"] == "365" and res["clamped"]

        res2 = rs.validate_value(spec, "-3")
        assert res2["ok"] and res2["value"] == "0" and res2["clamped"]

    def test_validate_int_rejects_non_numeric(self):
        res = rs.validate_value({"type": "int", "min": 0, "max": 10}, "abc")
        assert not res["ok"]

    def test_validate_str_rejects_empty(self):
        res = rs.validate_value({"type": "str"}, "   ")
        assert not res["ok"]

    def test_validate_str_ok(self):
        res = rs.validate_value({"type": "str"}, "hello")
        assert res["ok"] and res["value"] == "hello"

    def test_get_int_fallback_and_cache(self):
        assert rs.get_int("missing", 7) == 7
        rs._cache["k"] = "15"
        assert rs.get_int("k", 7) == 15
        rs._cache["bad"] = "xyz"
        assert rs.get_int("bad", 3) == 3

    def test_mask_chat_id(self):
        assert rs.mask_chat_id("123456789") == "\u2022\u2022\u2022\u20226789"
        assert rs.mask_chat_id("12") == "\u2022\u2022\u2022\u2022"

    @pytest.mark.asyncio
    async def test_load_overrides_success(self, clean_rs_cache):
        db = MagicMock()
        db.get_app_settings = AsyncMock(return_value={"k": "v"})
        result = await rs.load_overrides(db)
        assert result == {"k": "v"}
        assert rs.get_overrides() == {"k": "v"}

    @pytest.mark.asyncio
    async def test_load_overrides_db_failure_keeps_cache(self):
        rs._cache["keep"] = "me"
        db = MagicMock()
        db.get_app_settings = AsyncMock(side_effect=RuntimeError("db down"))
        result = await rs.load_overrides(db)
        assert result == {"keep": "me"}

    def test_build_payload_never_leaks_secret_values(self):
        enc_token = rs.encrypt_secret("super-secret-token")
        db_values = {
            "telegram_bot_token": enc_token,
            "telegram_chat_id": rs.encrypt_secret("123456789"),
            "alert_history_retention_days": "2",
        }
        defaults = {"alert_history_retention_days": 7}
        payload = rs.build_settings_payload(db_values, defaults)
        items = {it["key"]: it for it in payload["settings"]}

        token_item = items["telegram_bot_token"]
        assert token_item["secret"] is True
        assert token_item["value"] is None
        assert token_item["set"] is True
        assert token_item["persisted"] is True
        assert "super-secret" not in str(payload)

        chat_item = items["telegram_chat_id"]
        assert chat_item["masked"] == "\u2022\u2022\u2022\u20226789"
        assert "123456789" not in str(payload)

        ret_item = items["alert_history_retention_days"]
        assert ret_item["value"] == "2"
        assert ret_item["overridden"] is True
        assert ret_item["default"] == 7

    def test_setting_specs_complete(self):
        keys = {s["key"] for s in rs.SETTING_SPECS}
        assert {
            "alert_history_retention_days", "dashboard_refresh_seconds",
            "anomaly_feed_limit", "telegram_bot_token", "telegram_chat_id",
        } <= keys


# ====================================================================
# 4. Notifier.reconfigure
# ====================================================================

class TestNotifierReconfigure:
    @pytest.mark.asyncio
    async def test_reconfigure_success(self):
        notifier = TelegramNotifier(MagicMock())
        old_bot = MagicMock()
        old_bot.shutdown = AsyncMock()
        notifier.bot = old_bot
        notifier.chat_id = "111"

        new_me = SimpleNamespace(username="new_bot")
        with patch("app.notifier.Bot") as mock_bot_cls:
            instance = mock_bot_cls.return_value
            instance.get_me = AsyncMock(return_value=new_me)
            instance.shutdown = AsyncMock()

            result = await notifier.reconfigure(token="new-token", chat_id="67890")

        assert result["ok"] is True
        assert result["bot_username"] == "new_bot"
        assert notifier.chat_id == "67890"
        assert notifier.bot is instance
        old_bot.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconfigure_invalid_token_keeps_old_state(self):
        notifier = TelegramNotifier(MagicMock())
        old_bot = MagicMock()
        notifier.bot = old_bot
        notifier.chat_id = "111"
        notifier.bot_username = "old_bot"

        with patch("app.notifier.Bot") as mock_bot_cls:
            instance = mock_bot_cls.return_value
            instance.get_me = AsyncMock(side_effect=RuntimeError("401 unauthorized"))
            instance.shutdown = AsyncMock()

            result = await notifier.reconfigure(token="bad", chat_id="67890")

        assert result["ok"] is False
        assert result["reason"] == "invalid_token"
        assert notifier.bot is old_bot          # state lama utuh
        assert notifier.chat_id == "111"
        assert notifier.bot_username == "old_bot"

    @pytest.mark.asyncio
    async def test_reconfigure_result_has_no_token(self):
        notifier = TelegramNotifier(MagicMock())
        with patch("app.notifier.Bot") as mock_bot_cls:
            instance = mock_bot_cls.return_value
            instance.get_me = AsyncMock(
                return_value=SimpleNamespace(username="u"))
            instance.shutdown = AsyncMock()
            result = await notifier.reconfigure(token="SECRET-TOKEN", chat_id="42")
        assert "SECRET-TOKEN" not in str(result)


# ====================================================================
# 5. Endpoint settings: GET & PUT
# ====================================================================

class TestSettingsEndpoints:
    def test_get_settings_shape(self, v26_client):
        resp = v26_client.get("/dashboard/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        items = body["data"]["settings"]
        keys = {it["key"] for it in items}
        assert "alert_history_retention_days" in keys
        assert "telegram_bot_token" in keys
        for it in items:
            if it["secret"]:
                assert it["value"] is None

    def test_get_settings_reflects_overrides(self, v26_client):
        v26_client._v26_mock_db.get_app_settings = AsyncMock(
            return_value={"alert_history_retention_days": "14"}
        )
        resp = v26_client.get("/dashboard/api/settings")
        items = {it["key"]: it for it in resp.json()["data"]["settings"]}
        ret = items["alert_history_retention_days"]
        assert ret["value"] == "14"
        assert ret["overridden"] is True

    def test_put_int_setting_clamps_and_persists(self, v26_client):
        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"alert_history_retention_days": "999"}},
        )
        body = resp.json()
        result = body["results"]["alert_history_retention_days"]
        assert result["ok"] is True
        assert result["warning"] is not None  # clamp warning
        # nilai yang dipersist 365 (bukan 999)
        args = v26_client._v26_mock_db.set_app_setting.await_args.args
        assert args == ("alert_history_retention_days", "365")
        # cache override ikut ter-update
        assert rs._cache["alert_history_retention_days"] == "365"

    def test_put_unknown_key_fails_gracefully(self, v26_client):
        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"nope_key": "1"}},
        )
        assert resp.json()["results"]["nope_key"]["ok"] is False

    def test_put_invalid_int_fails(self, v26_client):
        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"dashboard_refresh_seconds": "abc"}},
        )
        result = resp.json()["results"]["dashboard_refresh_seconds"]
        assert result["ok"] is False

    def test_put_chat_id_persists(self, v26_client):
        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"telegram_chat_id": "67890"}},
        )
        body = resp.json()
        result = body["results"]["telegram_chat_id"]
        assert result["ok"] is True
        args = v26_client._v26_mock_db.set_app_setting.await_args.args
        assert args == ("telegram_chat_id", "67890")

    def test_put_token_applies_and_persists_encrypted(self, v26_client):
        # chat id sudah tersimpan (terenkripsi)
        v26_client._v26_mock_db.get_app_settings = AsyncMock(
            return_value={"telegram_chat_id": rs.encrypt_secret("67890")}
        )
        mock_notifier = MagicMock()
        mock_notifier.reconfigure = AsyncMock(
            return_value={"ok": True, "bot_username": "nb", "chat_id_masked": "x"}
        )
        ui_routes.set_notifier(mock_notifier)

        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"telegram_bot_token": "live-token"}},
        )
        result = resp.json()["results"]["telegram_bot_token"]
        assert result["ok"] is True
        mock_notifier.reconfigure.assert_awaited_once_with(
            token="live-token", chat_id="67890"
        )
        # nilai tersimpan terenkripsi
        args = v26_client._v26_mock_db.set_app_setting.await_args.args
        assert args[0] == "telegram_bot_token"
        assert args[1].startswith("enc:v1:")
        assert "live-token" not in args[1]
        ui_routes.set_notifier(None)

    def test_put_invalid_token_not_persisted(self, v26_client):
        v26_client._v26_mock_db.get_app_settings = AsyncMock(
            return_value={"telegram_chat_id": "67890"}
        )
        mock_notifier = MagicMock()
        mock_notifier.reconfigure = AsyncMock(
            return_value={"ok": False, "reason": "invalid_token"}
        )
        ui_routes.set_notifier(mock_notifier)

        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"telegram_bot_token": "bad-token"}},
        )
        result = resp.json()["results"]["telegram_bot_token"]
        assert result["ok"] is False
        v26_client._v26_mock_db.set_app_setting.assert_not_awaited()
        ui_routes.set_notifier(None)

    def test_put_token_without_chat_id_rejected(self, v26_client):
        v26_client._v26_mock_db.get_app_settings = AsyncMock(return_value={})
        mock_notifier = MagicMock()
        mock_notifier.reconfigure = AsyncMock()
        ui_routes.set_notifier(mock_notifier)

        resp = v26_client.put(
            "/dashboard/api/settings",
            json={"updates": {"telegram_bot_token": "some-token"}},
        )
        result = resp.json()["results"]["telegram_bot_token"]
        assert result["ok"] is False
        assert (result["detail"] or {}).get("reason") == "missing_chat_id"
        mock_notifier.reconfigure.assert_not_awaited()
        ui_routes.set_notifier(None)


# ====================================================================
# 6. History filter endpoint + heatmap CSV + manifest
# ====================================================================

class TestFilterCsvManifest:
    def test_history_endpoint_passes_filters(self, v26_client):
        resp = v26_client.get(
            "/dashboard/api/alerts/history",
            params={"symbol": "pepeusdt", "hours": 12, "limit": 5},
        )
        body = resp.json()
        assert body["status"] == "success"
        assert body["filters"] == {"symbol": "PEPEUSDT", "hours": 12, "priority": None}
        kwargs = v26_client._v26_mock_db.get_alert_history.await_args.kwargs
        assert kwargs["symbol"] == "PEPEUSDT"
        assert kwargs["hours"] == 12
        assert kwargs["limit"] == 5

    def test_history_endpoint_without_filters(self, v26_client):
        resp = v26_client.get("/dashboard/api/alerts/history")
        body = resp.json()
        assert body["filters"] == {"symbol": None, "hours": None, "priority": None}

    def test_heatmap_csv_content(self, v26_client):
        v26_client._v26_mock_db.get_alert_heatmap = AsyncMock(return_value=[
            {"symbol": "PEPEUSDT", "hour": _utc(3), "count": 4, "severity": 2},
        ])
        resp = v26_client.get("/dashboard/api/alerts/heatmap.csv", params={"hours": 24})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        text = resp.text
        lines = text.strip().splitlines()
        assert lines[0] == "symbol,hour,alert_count,severity"
        assert "PEPEUSDT" in lines[1]
        assert ",4,2" in lines[1]

    def test_heatmap_csv_empty(self, v26_client):
        resp = v26_client.get("/dashboard/api/alerts/heatmap.csv")
        assert resp.status_code == 200
        assert resp.text.strip() == "symbol,hour,alert_count,severity"

    def test_manifest_is_served(self, v26_client):
        resp = v26_client.get("/dashboard/manifest.webmanifest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Crypto Oracle AI"
        assert data["start_url"] == "/dashboard"
        icons = data["icons"]
        assert any(ic["sizes"] == "192x192" for ic in icons)
        assert any(ic["sizes"] == "512x512" for ic in icons)

    def test_pwa_icons_served(self, v26_client):
        for size in (192, 512):
            resp = v26_client.get(f"/static/icons/icon-{size}.png")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/png"


# ====================================================================
# 7. Main: retensi membaca override runtime + restore Telegram
# ====================================================================

class TestMainRetentionOverride:
    def _make_app(self):
        from app.main import CryptoOracleApp
        app_orch = CryptoOracleApp()
        app_orch.db = MagicMock()
        app_orch.db.prune_alert_history = AsyncMock(return_value=5)
        app_orch.notifier = MagicMock()
        return app_orch

    @pytest.mark.asyncio
    async def test_override_used_over_env(self, clean_rs_cache):
        app_orch = self._make_app()
        with patch.object(rs, "get_int", return_value=2):
            deleted = await app_orch._prune_alert_history_once()
        assert deleted == 5
        app_orch.db.prune_alert_history.assert_awaited_once_with(2)

    @pytest.mark.asyncio
    async def test_zero_override_disables_prune(self, clean_rs_cache):
        app_orch = self._make_app()
        with patch.object(rs, "get_int", return_value=0):
            result = await app_orch._prune_alert_history_once()
        assert result is None
        app_orch.db.prune_alert_history.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fallback_to_env_when_no_override(self, clean_rs_cache):
        app_orch = self._make_app()
        with patch.object(rs, "get_int", return_value=9):
            await app_orch._prune_alert_history_once()
        app_orch.db.prune_alert_history.assert_awaited_once_with(9)

    @pytest.mark.asyncio
    async def test_apply_persisted_telegram_restores_chat_and_reconfigures(self):
        from app.main import CryptoOracleApp
        app_orch = CryptoOracleApp()
        app_orch.notifier = MagicMock()
        app_orch.notifier.chat_id = None
        app_orch.notifier.reconfigure = AsyncMock(
            return_value={"ok": True}
        )
        rs._cache["telegram_bot_token"] = rs.encrypt_secret("tok")
        rs._cache["telegram_chat_id"] = rs.encrypt_secret("42")
        try:
            await app_orch._apply_persisted_telegram_config()
        finally:
            rs._cache.clear()
        app_orch.notifier.reconfigure.assert_awaited_once_with(
            token="tok", chat_id="42"
        )
        assert app_orch.notifier.chat_id == "42"

    @pytest.mark.asyncio
    async def test_apply_persisted_noop_without_secrets(self):
        from app.main import CryptoOracleApp
        app_orch = CryptoOracleApp()
        app_orch.notifier = MagicMock()
        app_orch.notifier.reconfigure = AsyncMock()
        await app_orch._apply_persisted_telegram_config()
        app_orch.notifier.reconfigure.assert_not_awaited()


# ====================================================================
# 8. Retensi efektif: endpoint ikut membaca override runtime
# ====================================================================

class TestEffectiveRetention:
    def test_retention_endpoint_shows_override(self, v26_client, clean_rs_cache):
        rs._cache["alert_history_retention_days"] = "2"
        resp = v26_client.get("/dashboard/api/alerts/retention")
        assert resp.json()["data"]["retention_days"] == 2

    def test_prune_endpoint_default_uses_override(self, v26_client, clean_rs_cache):
        rs._cache["alert_history_retention_days"] = "3"
        v26_client._v26_mock_db.prune_alert_history = AsyncMock(return_value=7)
        resp = v26_client.post("/dashboard/api/alerts/prune", json={})
        body = resp.json()
        assert body["retention_days_used"] == 3
        v26_client._v26_mock_db.prune_alert_history.assert_awaited_once_with(3)


# ====================================================================
# 9. Frontend regression guard: selector [hidden] tidak boleh korup
# ====================================================================

HIDDEN_SEL = "[" + "hidden]"  # selector atribut valid (dibangun agar aman dari mangling)


class TestDashboardHtmlIntegrity:
    """Guard integritas selector CSS atribut hidden (diperbaiki ronde-8).

    Sejak v2.3 selector dalam file TERCATAT korup (karakter pembuka
    atribut + huruf h hilang) dan guard lama justru menegaskan bentuk
    korup itu. Di browser modern elemen tetap ter-hidden berkat UA rule
    display:none !important untuk atribut hidden sehingga tidak terasa
    di QA, tetapi rule invalid adalah dead code & melemahkan browser
    lama. Guard kini mewajibkan bentuk VALID dan menolak bentuk korup.
    """

    def _html(self) -> str:
        from pathlib import Path
        tpl = Path(__file__).resolve().parent.parent / "app" / "ui" / "templates" / "dashboard.html"
        return tpl.read_text(encoding="utf-8")

    def test_hidden_display_none_rules_valid(self):
        html = self._html()
        targets = [cls + HIDDEN_SEL for cls in (".error-banner", ".modal-backdrop", ".offline-banner")]
        for sel in targets:
            assert f"{sel} {{ display: none; }}" in html, f"missing rule: {sel}"

    def test_no_corrupted_hidden_selectors(self):
        import re
        html = self._html()
        # Buang dulu semua bentuk valid (klass + [hidden]) lalu pastikan
        # tidak ada sisa pola 'klass+idden]' tanpa pembuka atribut.
        residual = html.replace(HIDDEN_SEL, "@@OK@@")
        corrupted = re.findall(r"[a-z-]+idden\]", residual)
        assert not corrupted, f"corrupted selector(s) found: {corrupted}"


# ====================================================================
# 10. Versi aplikasi
# ====================================================================

class TestVersionV26:
    def test_app_version_bumped(self):
        from app.main import app as fastapi_app
        assert fastapi_app.version >= "2.7.0"
