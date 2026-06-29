import logging
import sys
from typing import Optional
from datetime import datetime

def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    Setup structured logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path to write logs
    
    Returns:
        Configured logger instance
    """
    
    # Create custom formatter for JSON-like structured logs
    class StructuredFormatter(logging.Formatter):
        def format(self, record):
            timestamp = datetime.utcnow().isoformat() + "Z"
            return f'{{"timestamp": "{timestamp}", "level": "{record.levelname}", "module": "{record.module}", "message": "{record.getMessage()}"}}'
    
    # Create console formatter for better readability during development
    class ConsoleFormatter(logging.Formatter):
        def format(self, record):
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            return f"[{timestamp}] [{record.levelname:8}] [{record.module:15}] {record.getMessage()}"
    
    # Get root logger
    logger = logging.getLogger("crypto_oracle")
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.setFormatter(ConsoleFormatter())
    logger.addHandler(console_handler)
    
    # Create file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(StructuredFormatter())
        logger.addHandler(file_handler)
    
    return logger

# Global logger instance
logger = setup_logging()

def get_logger() -> logging.Logger:
    """Get the global logger instance."""
    return logger

def update_logger_config(log_level: str = "INFO", log_file: Optional[str] = None):
    """Update logger configuration dynamically."""
    global logger
    logger = setup_logging(log_level, log_file)
    return logger
