"""
Telegram Notifier for Crypto Oracle AI
Sends trading signals to Telegram
"""
import logging
from typing import Dict, Any, Optional

from telegram import Bot
from telegram.error import TelegramError
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Sends trading signals and alerts to Telegram
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.bot: Optional[Bot] = None
        self.chat_id = self.settings.telegram_chat_id
        
        if not self.settings.telegram_bot_token:
            logger.warning("Telegram bot token not configured")
        
        if not self.chat_id:
            logger.warning("Telegram chat ID not configured")
    
    async def start(self) -> None:
        """Initialize the Telegram bot"""
        if self.settings.telegram_bot_token:
            self.bot = Bot(token=self.settings.telegram_bot_token)
            
            try:
                # Test connection
                me = await self.bot.get_me()
                logger.info(f"Telegram bot initialized: @{me.username}")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
                self.bot = None
        else:
            logger.warning("Telegram notifier disabled - no bot token")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.bot:
            await self.bot.session.close()
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
        from datetime import datetime
        import pytz
        
        utc_now = datetime.utcnow()
        wib_tz = pytz.timezone('Asia/Jakarta')
        wib_time = utc_now.replace(tzinfo=pytz.utc).astimezone(wib_tz)
        
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
