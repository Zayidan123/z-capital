"""
Configuration loader for Crypto Oracle AI
Loads environment variables and provides validated settings
"""
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Database Configuration
    database_url: str = Field(
        default="postgresql://user:password@localhost:5432/crypto_oracle",
        description="PostgreSQL connection URL",
    )

    # Telegram Configuration
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram Bot API Token",
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram Chat ID for notifications",
    )

    # Etherscan Configuration
    etherscan_api_key: Optional[str] = Field(
        default=None,
        description="Etherscan API Key",
    )
    etherscan_base_url: str = Field(
        default="https://api.etherscan.io/api",
        description="Etherscan API Base URL",
    )

    # CryptoPanic Configuration
    cryptopanic_api_key: Optional[str] = Field(
        default=None,
        description="CryptoPanic API Key",
    )
    cryptopanic_base_url: str = Field(
        default="https://cryptopanic.com/api/v1",
        description="CryptoPanic API Base URL",
    )

    # Binance Configuration
    binance_ws_url: str = Field(
        default="wss://stream.binance.com:9443/stream?streams=!ticker@arr",
        description="Binance WebSocket URL",
    )

    # Application Settings
    volume_spike_threshold: float = Field(
        default=300.0,
        description="Volume spike threshold percentage",
    )
    volume_window_minutes: int = Field(
        default=5,
        description="Time window for volume calculation in minutes",
        gt=0,
    )
    health_check_port: int = Field(
        default=8080,
        description="Port for health check endpoint",
        ge=1,
        le=65535,
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )

    # Redis Configuration (Optional)
    redis_host: Optional[str] = Field(
        default=None,
        description="Redis host for caching and rate limiting",
    )
    redis_port: int = Field(
        default=6379,
        description="Redis port",
        ge=1,
        le=65535,
    )
    redis_url: Optional[str] = Field(
        default=None,
        description="Full Redis connection URL (overrides host/port)",
    )

    # Dashboard Security (Optional)
    dashboard_api_key: Optional[str] = Field(
        default=None,
        description=(
            "API key required in the X-API-Key header for dashboard API endpoints. "
            "Leave unset (None) to disable authentication (default, for local use)."
        ),
    )

    # Dashboard Rate Limiting (per-IP, sliding window, in-memory)
    dashboard_rate_limit: int = Field(
        default=120,
        ge=0,
        description=(
            "Max API requests per IP per window for /dashboard/api/* endpoints. "
            "Set 0 to disable rate limiting (default 120/min)."
        ),
    )
    dashboard_rate_limit_window: int = Field(
        default=60,
        gt=0,
        description="Rate limit window in seconds (default 60).",
    )

    # Alert history retention (v2.5): housekeeping tabel alert_history
    alert_history_retention_days: int = Field(
        default=7,
        ge=0,
        description=(
            "Alert history rows older than this many days are pruned "
            "periodically by the background retention loop. "
            "Set 0 to disable automatic pruning (default 7 days)."
        ),
    )
    alert_retention_interval_minutes: int = Field(
        default=60,
        gt=0,
        description="How often the retention loop runs, in minutes (default 60).",
    )

    def get_redis_url(self) -> str:
        """Build the Redis connection URL from settings"""
        if self.redis_url:
            return self.redis_url
        if self.redis_host:
            return f"redis://{self.redis_host}:{self.redis_port}"
        return "redis://localhost:6379"


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance"""
    return settings
