"""
Runtime Settings (v2.6)
Konfigurasi yang bisa diubah saat aplikasi berjalan lewat dashboard dan
tetap bertahan setelah restart (tersimpan di tabel app_settings).

Keamanan secret (telegram bot token):
- Token TIDAK pernah dikirim balik ke client (write-only).
- Token disimpan TERENKRIPSI (Fernet) di DB. Kunci enkripsi diturunkan
  secara deterministik dari DASHBOARD_SECRET_SALT (atau database_url
  bila salt tidak diset) sehingga tidak butuh konfigurasi tambahan,
  namun tidak lagi berupa plaintext di dalam database.
"""
import base64
import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ===== Spesifikasi key runtime settings =====
# type: int | str | secret
# min/max hanya dipakai untuk type int (nilai di-clamp, bukan ditolak,
# agar UX dashboard tetap ramah).
SETTING_SPECS: List[Dict[str, Any]] = [
    {
        "key": "alert_history_retention_days",
        "type": "int",
        "min": 0,
        "max": 365,
        "default": 7,
        "description": "Auto-prune alert_history older than N days (0 = off).",
    },
    {
        "key": "dashboard_refresh_seconds",
        "type": "int",
        "min": 10,
        "max": 600,
        "default": 30,
        "description": "How often the dashboard polls/refreshes panels (seconds).",
    },
    {
        "key": "anomaly_feed_limit",
        "type": "int",
        "min": 10,
        "max": 200,
        "default": 25,
        "description": "Max rows fetched for the anomaly feed table.",
    },
    {
        "key": "telegram_bot_token",
        "type": "secret",
        "default": None,
        "description": (
            "Telegram bot API token (write-only). Stored encrypted; "
            "never returned by the API. Applied to the running notifier."
        ),
    },
    {
        "key": "telegram_chat_id",
        "type": "secret",
        "default": None,
        "description": (
            "Telegram chat id for notifications (write-only, masked in "
            "responses). Applied to the running notifier."
        ),
    },
    {
        "key": "webhook_url",
        "type": "secret",
        "default": None,
        "description": (
            "Webhook endpoint for alert delivery (write-only). Stored "
            "encrypted; only scheme://host is shown. Triggered alerts are "
            "POSTed here as JSON (v2.8)."
        ),
    },
]

SPECS_BY_KEY: Dict[str, Dict[str, Any]] = {s["key"]: s for s in SETTING_SPECS}

# Prefix kolom DB untuk nilai terenkripsi
_ENCRYPTED_PREFIX = "enc:v1:"

# Cache override in-memory: meminimalkan query DB berulang (mis. loop
# retensi) dan menjadi fallback bila DB sempat gagal.
_cache: Dict[str, str] = {}


def _fernet():
    """Bangun Fernet dari kunci derivasi deterministik (tanpa config extra)."""
    from cryptography.fernet import Fernet
    from app.config import get_settings

    settings = get_settings()
    secret_source = (
        getattr(settings, "dashboard_secret_salt", None)
        or settings.database_url
        or "crypto-oracle-fallback-salt"
    )
    digest = hashlib.sha256(("crypto-oracle:" + secret_source).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Enkripsi secret untuk disimpan di DB (format enc:v1:<token>)."""
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _ENCRYPTED_PREFIX + token


def decrypt_secret(stored: str) -> Optional[str]:
    """Dekripsi secret dari DB. None bila format/ciphertext tidak valid."""
    if not stored or not stored.startswith(_ENCRYPTED_PREFIX):
        return None
    try:
        token = stored[len(_ENCRYPTED_PREFIX):]
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception as e:  # noqa: BLE001 - kegagalan dekripsi tidak boleh crash
        logger.warning(f"Failed to decrypt stored secret: {e}")
        return None


def is_encrypted(value: str) -> bool:
    """True bila nilai tersimpan dalam format terenkripsi enc:v1:*."""
    return bool(value) and value.startswith(_ENCRYPTED_PREFIX)


def mask_chat_id(chat_id: str) -> str:
    """Samarkan chat id untuk ditampilkan (hanya 4 karakter terakhir)."""
    cid = str(chat_id)
    return ("\u2022\u2022\u2022\u2022" + cid[-4:]) if len(cid) > 4 else "\u2022\u2022\u2022\u2022"


def validate_value(spec: Dict[str, Any], raw: str) -> Dict[str, Any]:
    """Validasi + normalisasi satu nilai setting.

    Returns:
        {ok, value, clamped, warning} - value bertipe str siap disimpan.
    """
    if spec["type"] == "int":
        try:
            num = int(str(raw).strip())
        except (ValueError, TypeError):
            return {"ok": False, "warning": "must be an integer"}
        lo, hi = spec["min"], spec["max"]
        clamped = max(lo, min(num, hi))
        warning = None
        if clamped != num:
            warning = f"clamped to {clamped} (allowed {lo}..{hi})"
        return {"ok": True, "value": str(clamped), "clamped": clamped != num, "warning": warning}
    # str & secret: tidak boleh kosong, tidak ada batas panjang keras
    text = str(raw).strip()
    if not text:
        return {"ok": False, "warning": "must not be empty"}
    return {"ok": True, "value": text, "clamped": False, "warning": None}


async def load_overrides(db: Any) -> Dict[str, str]:
    """Muat override tersimpan dari DB ke cache in-memory.

    DB gagal -> cache sebelumnya dipertahankan (best-effort).
    """
    try:
        stored = await db.get_app_settings()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Runtime settings load failed, keeping cache: {e}")
        return dict(_cache)
    _cache.clear()
    _cache.update(stored)
    return dict(_cache)


def get_overrides() -> Dict[str, str]:
    """Salinan cache override saat ini (nilai mentah, masih terenkripsi bila secret)."""
    return dict(_cache)


def get_int(key: str, fallback: int) -> int:
    """Ambil nilai int override untuk `key`; fallback bila tidak ada/tidak valid.

    Dipakai loop retensi di main.py tiap siklus - membaca cache (tanpa DB)
    agar loop tidak menambah beban query.
    """
    raw = _cache.get(key)
    if raw is None:
        return fallback
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return fallback


def get_string(key: str, fallback: Optional[str] = None) -> Optional[str]:
    """Ambil nilai string override (menangani nilai terenkripsi otomatis)."""
    raw = _cache.get(key)
    if raw is None:
        return fallback
    if is_encrypted(raw):
        return decrypt_secret(raw)
    return raw


def build_settings_payload(db_values: Dict[str, str], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Susun payload GET /api/settings yang aman untuk client.

    - secret TIDAK pernah disertakan nilainya (hanya flag set/persisted)
    - chat_id ditampilkan dalam bentuk tersamarkan
    - tiap key dilengkapi default, tipe, batasan, dan status override
    """
    items = []
    for spec in SETTING_SPECS:
        key = spec["key"]
        raw = db_values.get(key)
        secret = spec["type"] == "secret"
        overridden = key in db_values
        item: Dict[str, Any] = {
            "key": key,
            "type": spec["type"],
            "description": spec["description"],
            "overridden": overridden,
            "secret": secret,
            "default": defaults.get(key, spec.get("default")),
        }
        if secret:
            item["set"] = raw is not None
            item["persisted"] = overridden
            item["value"] = None
            if key == "telegram_chat_id":
                plain = decrypt_secret(raw) if (raw and is_encrypted(raw)) else raw
                item["masked"] = mask_chat_id(plain) if plain else None
            elif key == "webhook_url":
                # v2.8: hanya scheme://host yang tampil (path sering
                # memuat token unik). Plaintext TIDAK pernah dikirim.
                from app.notifier import mask_webhook_url

                plain = decrypt_secret(raw) if (raw and is_encrypted(raw)) else raw
                item["masked"] = mask_webhook_url(plain) if plain else None
        else:
            item["value"] = raw if raw is not None else item["default"]
            item["persisted"] = overridden
            if spec["type"] == "int":
                item["min"] = spec["min"]
                item["max"] = spec["max"]
        items.append(item)
    return {"settings": items}


def defaults_from_env() -> Dict[str, Any]:
    """Default efektif tiap key: dari env settings bila tersedia, else spec."""
    from app.config import get_settings

    settings = get_settings()
    return {
        "alert_history_retention_days": settings.alert_history_retention_days,
        "dashboard_refresh_seconds": 30,
        "anomaly_feed_limit": 25,
        "telegram_bot_token": None,
        "telegram_chat_id": None,
    }
