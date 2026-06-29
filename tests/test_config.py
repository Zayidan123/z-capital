"""
Tests for the config module
"""
import pytest
from app.config import settings


class TestSettings:
    """Test configuration settings"""
    
    def test_settings_loaded(self):
        """Test that settings can be loaded"""
        assert settings is not None
    
    def test_telegram_bot_token_type(self):
        """Test Telegram bot token is string or None"""
        assert settings.telegram_bot_token is None or isinstance(settings.telegram_bot_token, str)
    
    def test_telegram_chat_id_type(self):
        """Test Telegram chat ID is string or None"""
        assert settings.telegram_chat_id is None or isinstance(settings.telegram_chat_id, str)
    
    def test_database_url_type(self):
        """Test database URL is string"""
        assert isinstance(settings.database_url, str)
    
    def test_volume_spike_threshold(self):
        """Test volume spike threshold is positive"""
        assert settings.volume_spike_threshold > 0
    
    def test_default_log_level(self):
        """Test default log level"""
        assert settings.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
