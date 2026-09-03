"""
Tests for the config module
"""
import pytest
from app.config import settings, Settings, get_settings


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

    def test_get_settings_singleton(self):
        """Test get_settings returns the same instance"""
        assert get_settings() is settings

    def test_get_redis_url_from_host(self):
        """Test Redis URL built from host/port when redis_url not set"""
        s = Settings(redis_host="redis.example.com", redis_port=6380, _env_file=None)
        assert s.get_redis_url() == "redis://redis.example.com:6380"

    def test_get_redis_url_direct(self):
        """Test Redis URL returned directly when provided"""
        s = Settings(redis_url="redis://custom:1234", _env_file=None)
        assert s.get_redis_url() == "redis://custom:1234"

    def test_get_redis_url_default(self):
        """Test Redis URL default when nothing configured"""
        s = Settings(_env_file=None)
        assert s.get_redis_url() == "redis://localhost:6379"
