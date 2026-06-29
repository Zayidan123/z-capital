"""
Configuration loader for Crypto Oracle AI
Loads environment variables and provides validated settings
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database Configuration
    database_url: str = Field(
        default="postgresql://user:password@localhost:5432/crypto_oracle",
        description="PostgreSQL connection URL"
    )
    
    # Telegram Configuration
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram Bot API Token"
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram Chat ID for notifications"
    )
    
    # Etherscan Configuration
    etherscan_api_key: Optional[str] = Field(
        default=None,
        description="Etherscan API Key"
    )
    etherscan_base_url: str = Field(
        default="https://api.etherscan.io/api",
        description="Etherscan API Base URL"
    )
    
    # CryptoPanic Configuration
    cryptopanic_api_key: Optional[str] = Field(
        default=None,
        description="CryptoPanic API Key"
    )
    cryptopanic_base_url: str = Field(
        default="https://cryptopanic.com/api/v1",
        description="CryptoPanic API Base URL"
    )
    
    # Binance Configuration
    binance_ws_url: str = Field(
        default="wss://stream.binance.com:9443/stream?streams=!ticker@arr",
        description="Binance WebSocket URL"
    )
    
    # Application Settings
    volume_spike_threshold: float = Field(
        default=300.0,
        description="Volume spike threshold percentage"
    )
    volume_window_minutes: int = Field(
        default=5,
        description="Time window for volume calculation in minutes"
    )
    health_check_port: int = Field(
        default=8080,
        description="Port for health check endpoint"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance"""
    return settings
