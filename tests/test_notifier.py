"""
Tests for the notifier module (TelegramNotifier)
"""
import pytest
from unittest.mock import MagicMock

from app.notifier import TelegramNotifier


@pytest.fixture
def notifier():
    """Notifier dengan DB mock (tanpa token Telegram)"""
    return TelegramNotifier(db=MagicMock())


class TestTelegramNotifier:
    """Test notifier operations"""

    def test_notifier_initialization(self, notifier):
        """Test notifier can be initialized"""
        assert notifier is not None
        assert notifier.bot is None

    @pytest.mark.asyncio
    async def test_send_signal_without_token_returns_none(self, notifier):
        """Tanpa token, send_signal harus return None tanpa crash"""
        result = await notifier.send_signal({
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "volume_spike": 350.0,
            "reasons": ["Volume naik 350%"],
            "confirmed": True,
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_send_signal_unconfirmed_skipped(self, notifier):
        """Sinyal tidak confirmed -> skip notifikasi"""
        result = await notifier.send_signal({
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "volume_spike": 350.0,
            "reasons": [],
            "confirmed": False,
        })
        assert result is None

    def test_format_signal_message(self, notifier):
        """Test message formatting untuk Telegram"""
        message = notifier._format_signal_message(
            symbol="ETHUSDT",
            price=3000.0,
            volume_spike=400.0,
            reasons=["Smart money terdeteksi beli", "Volume naik 400%"],
            confidence=0.7,
        )
        assert "ETHUSDT" in message
        assert "3" in message
        assert "400" in message
        assert "Smart money terdeteksi beli" in message
        assert "<b>" in message  # HTML parse mode

    def test_format_signal_message_urgency_levels(self, notifier):
        """Emoji urgensi bergantung pada confidence"""
        high = notifier._format_signal_message("A", 1.0, 300, [], 0.9)
        medium = notifier._format_signal_message("A", 1.0, 300, [], 0.6)
        low = notifier._format_signal_message("A", 1.0, 300, [], 0.3)
        assert "🚨" in high
        assert "⚠️" in medium
        assert "📊" in low

    def test_get_current_time_wib(self, notifier):
        """Test konversi waktu ke WIB"""
        time_str = notifier._get_current_time()
        assert "WIB" in time_str

    @pytest.mark.asyncio
    async def test_send_system_alert_without_token(self, notifier):
        """System alert tanpa token tidak boleh crash"""
        await notifier.send_system_alert("TEST", "message")  # tidak raise
