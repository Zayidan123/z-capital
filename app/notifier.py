"""
Notification channels for Crypto Oracle AI
- TelegramNotifier: sends trading signals to Telegram
- WebhookDispatcher: posts alert payloads to an arbitrary HTTP endpoint (v2.8)
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from urllib.parse import urlsplit

import httpx

from telegram import Bot
from telegram.error import TelegramError
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


def mask_webhook_url(url: str) -> Optional[str]:
    """Samarkan webhook URL utk ditampilkan di dashboard (v2.8).

    Hanya scheme + host yang tampil; path & query disembunyikan karena
    sering memuat token unik (mis. https://hooks.example.com/TOKEN/...).
    Bila host tidak bisa diparse, kembalikan None (bukan URL mentah).
    """
    if not url:
        return None
    try:
        parts = urlsplit(str(url))
        if not parts.netloc:
            return None
        return f"{parts.scheme or 'https'}://{parts.netloc}"
    except Exception:  # noqa: BLE001
        return None


class WebhookDispatcher:
    """Kirim alert sebagai JSON POST ke endpoint HTTP arbitrary (v2.8).

    Desain:
    - URL TIDAK pernah dikembalikan utuh oleh get_status() - hanya host
      tersamarkan (path sering berisi token rahasia).
    - dispatch() fire-and-forget friendly: timeout ketat (10s) + hasil
      berupa dict {ok, status_code, reason}; TIDAK pernah raise.
    - transport bisa diinjeksi (httpx.MockTransport) untuk testing.
    - v2.9: retry otomatis dengan backoff - percobaan gagal dicoba lagi
      hingga max_attempts (jeda backoff_seconds di antaranya). Hasil
      mencatat attempts (jumlah percobaan) + duration_ms (total waktu).
    """

    def __init__(
        self,
        url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.url = str(url).strip()
        self._transport = transport
        self.max_attempts = max(1, min(int(max_attempts), 5))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.last_result: Optional[Dict[str, Any]] = None

    def get_status(self) -> Dict[str, Any]:
        """Status aman utk dashboard: configured + host tersamarkan."""
        return {
            "configured": bool(self.url),
            "url_masked": mask_webhook_url(self.url),
            "last_result": self.last_result,
        }

    def _build_payload(self, alert: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Payload standar webhook. Bila alert kosong -> payload test."""
        base: Dict[str, Any] = {
            "source": "z-capital",
            "type": "alert.test" if not alert else "alert.triggered",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if alert:
            base["alert"] = {
                "rule": alert.get("rule"),
                "priority": alert.get("priority"),
                "symbol": alert.get("symbol"),
                "channels": alert.get("channels", []),
                "timestamp": alert.get("timestamp"),
                "data": alert.get("data", {}),
            }
        else:
            base["message"] = "Crypto Oracle AI webhook test - konfigurasi OK."
        return base

    async def _attempt_once(self, alert: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Satu percobaan POST (tanpa retry). Selalu kembalikan hasil."""
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                transport=self._transport,
            ) as client:
                resp = await client.post(
                    self.url,
                    json=self._build_payload(alert),
                    headers={"X-ZCapital-Event": "alert" if alert else "test"},
                )
            ok = 200 <= resp.status_code < 300
            return {
                "ok": ok,
                "status_code": resp.status_code,
                "reason": None if ok else f"http_{resp.status_code}",
            }
        except httpx.TimeoutException:
            return {"ok": False, "status_code": None, "reason": "timeout"}
        except Exception as e:  # noqa: BLE001 - webhook gagal tidak boleh crash
            logger.warning(f"Webhook dispatch failed: {e}")
            return {"ok": False, "status_code": None, "reason": "error", "detail": str(e)}

    async def dispatch(self, alert: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """POST payload ke webhook dengan retry + backoff (v2.9).

        Selalu mengembalikan hasil, tak pernah raise. Percobaan gagal
        diulang hingga max_attempts dengan jeda backoff_seconds * n.
        Result: {ok, status_code, reason?, attempts, duration_ms}.
        """
        if not self.url:
            result = {
                "ok": False, "status_code": None, "reason": "not_configured",
                "attempts": 0, "duration_ms": 0,
            }
            self.last_result = result
            return result

        started = time.monotonic()
        result: Dict[str, Any] = {"ok": False, "status_code": None, "reason": "not_configured"}
        for attempt in range(1, self.max_attempts + 1):
            result = await self._attempt_once(alert)
            result["attempts"] = attempt
            if result.get("ok"):
                break
            if attempt < self.max_attempts and self.backoff_seconds > 0:
                await asyncio.sleep(self.backoff_seconds * attempt)
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        self.last_result = result
        return result

    async def test_send(self) -> Dict[str, Any]:
        """Kirim payload test (dipakai endpoint POST /api/webhook/test)."""
        return await self.dispatch(alert=None)


class TelegramNotifier:
    """
    Sends trading signals and alerts to Telegram
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.bot: Optional[Bot] = None
        self.chat_id = self.settings.telegram_chat_id
        self.bot_username: Optional[str] = None
        
        if not self.settings.telegram_bot_token:
            logger.warning("Telegram bot token not configured")
        
        if not self.chat_id:
            logger.warning("Telegram chat ID not configured")

    def get_status(self) -> Dict[str, Any]:
        """Status konfigurasi Telegram yang aman untuk dashboard (v2.5).

        Token TIDAK PERNAH disertakan dalam output - hanya metadata:
        - configured: bot + chat_id tersedia
        - bot_username: username bot (diisi saat start() berhasil)
        - chat_id_masked: chat id disamarkan (hanya 4 karakter terakhir)
        """
        chat_id_masked = None
        if self.chat_id:
            cid = str(self.chat_id)
            chat_id_masked = ("\u2022\u2022\u2022\u2022" + cid[-4:]) if len(cid) > 4 else "\u2022\u2022\u2022\u2022"
        return {
            "configured": bool(self.bot and self.chat_id),
            "bot_username": self.bot_username,
            "chat_id_masked": chat_id_masked,
        }
    
    async def start(self) -> None:
        """Initialize the Telegram bot"""
        if self.settings.telegram_bot_token:
            self.bot = Bot(token=self.settings.telegram_bot_token)

            try:
                # Test connection
                me = await self.bot.get_me()
                self.bot_username = getattr(me, "username", None)
                logger.info(f"Telegram bot initialized: @{self.bot_username}")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
                self.bot = None
                self.bot_username = None
        else:
            logger.warning("Telegram notifier disabled - no bot token")

    async def reconfigure(self, token: str, chat_id: str) -> Dict[str, Any]:
        """Konfigurasi ulang bot saat runtime (v2.6) tanpa restart proses.

        Membuat Bot baru dari token yang diberikan, memverifikasi via
        get_me(), lalu memasang chat_id baru. Bila verifikasi gagal,
        state lama DIPERTAHANKAN (token lama tetap aktif) dan dict hasil
        berisi ok=False + reason.

        Returns:
            {ok, bot_username, chat_id_masked, reason?} - token tidak
            pernah disertakan dalam hasil.
        """
        old_bot = self.bot

        candidate = Bot(token=token)
        try:
            me = await candidate.get_me()
        except Exception as e:
            logger.warning(f"Runtime reconfigure rejected: invalid bot token ({e})")
            try:
                await candidate.shutdown()
            except Exception:
                pass
            return {
                "ok": False,
                "reason": "invalid_token",
                "detail": str(e),
                "bot_username": self.bot_username,
                "chat_id_masked": self.get_status().get("chat_id_masked"),
            }

        # Sukses: shutdown bot lama (best-effort) lalu pasang kandidat
        if old_bot is not None:
            try:
                await old_bot.shutdown()
            except Exception as e:
                logger.debug(f"Old telegram bot shutdown error: {e}")
        self.bot = candidate
        self.bot_username = getattr(me, "username", None)
        self.chat_id = str(chat_id).strip()
        logger.info(f"Telegram notifier reconfigured at runtime: @{self.bot_username}")
        return {
            "ok": True,
            "bot_username": self.bot_username,
            "chat_id_masked": self.get_status().get("chat_id_masked"),
        }
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.bot:
            try:
                # python-telegram-bot v20+: gunakan shutdown(), bukan session.close()
                await self.bot.shutdown()
            except Exception as e:
                logger.debug(f"Error shutting down Telegram bot: {e}")
        logger.info("Telegram notifier stopped")
    
    async def send_signal(self, analysis_result: Dict[str, Any]) -> Optional[int]:
        """
        Send a trading signal to Telegram
        
        Args:
            analysis_result: Analysis result from analyzer.py
        
        Returns:
            Message ID if sent successfully, None otherwise
        """
        if not self.bot or not self.chat_id:
            logger.warning("Telegram notifier not configured")
            return None
        
        if not analysis_result.get('confirmed', False):
            logger.debug(f"Signal not confirmed for {analysis_result.get('symbol')}, skipping notification")
            return None
        
        symbol = analysis_result.get('symbol', 'UNKNOWN')
        price = analysis_result.get('price', 0)
        volume_spike = analysis_result.get('volume_spike', 0)
        reasons = analysis_result.get('reasons', [])
        
        # Format the message
        message = self._format_signal_message(
            symbol=symbol,
            price=price,
            volume_spike=volume_spike,
            reasons=reasons,
            confidence=analysis_result.get('confidence_score', 0)
        )
        
        try:
            # Send message
            response = await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            
            message_id = response.message_id
            
            # Log to database
            await self.db.log_signal(
                symbol=symbol,
                signal_type='PUMP_ALERT',
                message=message,
                status='sent',
                telegram_message_id=message_id
            )
            
            logger.info(f"Signal sent to Telegram: {symbol} (Message ID: {message_id})")
            return message_id
            
        except TelegramError as e:
            logger.error(f"Telegram error sending signal: {e}")
            
            # Log failed signal
            await self.db.log_signal(
                symbol=symbol,
                signal_type='PUMP_ALERT',
                message=message,
                status='failed'
            )
            
            return None
        except Exception as e:
            logger.error(f"Unexpected error sending signal: {e}")
            return None
    
    def _format_signal_message(
        self,
        symbol: str,
        price: float,
        volume_spike: float,
        reasons: list,
        confidence: float
    ) -> str:
        """Format the signal message for Telegram"""
        
        # Build reasons string
        reasons_str = "\n".join([f"• {reason}" for reason in reasons])
        
        # Determine emoji based on confidence
        if confidence >= 0.7:
            alert_emoji = "🚨"
            urgency = "HIGH"
        elif confidence >= 0.5:
            alert_emoji = "⚠️"
            urgency = "MEDIUM"
        else:
            alert_emoji = "📊"
            urgency = "LOW"
        
        message = f"""
{alert_emoji} <b>SINYAL: POTENSI PUMP {symbol}</b> {alert_emoji}

<b>Urgensi:</b> {urgency}
<b>Confidence:</b> {confidence:.0%}

📊 <b>Harga:</b> ${price:.8f}
📈 <b>Volume Spike:</b> +{volume_spike:.0f}%

💡 <b>Alasan:</b>
{reasons_str}

⚠️ <b>Saran Manajemen Resiko:</b>
• Max 2% modal per trade
• Stop Loss: -10%
• Take Profit: +20% / +40% / +60%
• Jangan FOMO!

⏰ <b>Waktu:</b> {self._get_current_time()}

<i>Disclaimer: Ini bukan financial advice. DYOR!</i>
""".strip()
        
        return message
    
    def _get_current_time(self) -> str:
        """Get current time in WIB (UTC+7)"""
        from zoneinfo import ZoneInfo
        
        wib_tz = ZoneInfo('Asia/Jakarta')
        wib_time = datetime.now(wib_tz)
        
        return wib_time.strftime('%d %b %Y, %H:%M WIB')
    
    async def send_test_message(self) -> bool:
        """Send a test message to verify Telegram configuration"""
        if not self.bot or not self.chat_id:
            return False
        
        try:
            message = """
✅ <b>Crypto Oracle AI - Test Message</b> ✅

Bot Telegram berhasil dikonfigurasi!

Sistem siap mengirim sinyal pump/dump.
Pastikan Anda telah mengisi semua API keys di .env file.

🔧 Status:
• Database: Connected
• Binance Streamer: Active
• Analyzer: Ready
• Telegram: Active

Good luck trading! 🚀
""".strip()
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            
            logger.info("Test message sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send test message: {e}")
            return False
    
    async def send_system_alert(self, alert_type: str, message: str) -> None:
        """Send a system alert (e.g., errors, maintenance)"""
        if not self.bot or not self.chat_id:
            return
        
        try:
            formatted_message = f"""
🔧 <b>System Alert: {alert_type}</b>

{message}

⏰ {self._get_current_time()}
""".strip()
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=formatted_message,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Failed to send system alert: {e}")
