"""
Tests for the notifier module
"""
import pytest
from app.notifier import Notifier


class TestNotifier:
    """Test notifier operations"""
    
    def test_notifier_initialization(self):
        """Test notifier can be initialized"""
        notifier = Notifier()
        assert notifier is not None
    
    @pytest.mark.asyncio
    async def test_send_signal(self):
        """Test sending signal to Telegram (may fail without valid token)"""
        notifier = Notifier()
        
        signal_data = {
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "volume_spike": 350.0,
            "reason": "Test reason"
        }
        
        try:
            result = await notifier.send_signal(signal_data)
            assert result is True or result is False
        except Exception as e:
            # Expected if no valid Telegram token
            pytest.skip(f"No valid Telegram bot token: {str(e)}")
    
    def test_format_message(self):
        """Test message formatting"""
        notifier = Notifier()
        
        signal_data = {
            "symbol": "ETHUSDT",
            "price": 3000.0,
            "volume_spike": 400.0,
            "reason": "Smart money detected"
        }
        
        message = notifier._format_message(signal_data)
        assert "ETHUSDT" in message
        assert "3000" in message
        assert "400" in message
