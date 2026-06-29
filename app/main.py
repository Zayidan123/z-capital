"""
Main Orchestrator for Crypto Oracle AI
Coordinates all modules and provides health check endpoint
"""
import asyncio
import logging
import sys
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.config import get_settings, Settings
from app.database import Database, get_database
from app.streamer import BinanceStreamer
from app.analyzer import DeepDiveAnalyzer
from app.notifier import TelegramNotifier
from app.ui.routes import router as ui_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class CryptoOracleApp:
    """
    Main application orchestrator
    Coordinates streamer, analyzer, and notifier
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.db: Optional[Database] = None
        self.streamer: Optional[BinanceStreamer] = None
        self.analyzer: Optional[DeepDiveAnalyzer] = None
        self.notifier: Optional[TelegramNotifier] = None
        self.running = False
    
    async def initialize(self) -> None:
        """Initialize all components"""
        logger.info("Initializing Crypto Oracle AI...")
        
        # Initialize database
        self.db = await get_database()
        logger.info("Database initialized")
        
        # Initialize notifier
        self.notifier = TelegramNotifier(self.db)
        await self.notifier.start()
        logger.info("Notifier initialized")
        
        # Initialize analyzer
        self.analyzer = DeepDiveAnalyzer(self.db)
        await self.analyzer.start()
        logger.info("Analyzer initialized")
        
        # Initialize streamer with anomaly callback
        self.streamer = BinanceStreamer(
            db=self.db,
            anomaly_callback=self._handle_anomaly
        )
        logger.info("Streamer initialized")
        
        logger.info("All components initialized successfully")
    
    async def _handle_anomaly(self, anomaly_data: dict) -> None:
        """
        Callback handler for detected anomalies
        Analyzes and sends notifications if confirmed
        """
        try:
            symbol = anomaly_data.get('symbol', 'UNKNOWN')
            logger.info(f"Handling anomaly for {symbol}")
            
            # Perform deep analysis
            analysis_result = await self.analyzer.analyze_anomaly(anomaly_data)
            
            # Add price to analysis result
            analysis_result['price'] = anomaly_data.get('price', 0)
            analysis_result['volume_spike'] = anomaly_data.get('volume_spike', 0)
            
            # Send notification if signal is confirmed
            if analysis_result.get('confirmed', False):
                logger.info(f"Confirmed signal for {symbol}, sending notification")
                await self.notifier.send_signal(analysis_result)
            else:
                logger.debug(f"Signal not confirmed for {symbol}")
                
        except Exception as e:
            logger.error(f"Error handling anomaly: {e}", exc_info=True)
    
    async def run(self) -> None:
        """Run the main application loop"""
        if not self.running:
            self.running = True
            
            # Start the streamer (this will run indefinitely)
            await self.streamer.start()
    
    async def stop(self) -> None:
        """Stop all components gracefully"""
        logger.info("Stopping Crypto Oracle AI...")
        self.running = False
        
        # Stop streamer
        if self.streamer:
            await self.streamer.stop()
        
        # Stop analyzer
        if self.analyzer:
            await self.analyzer.stop()
        
        # Stop notifier
        if self.notifier:
            await self.notifier.stop()
        
        # Close database connections
        if self.db:
            await self.db.disconnect()
        
        logger.info("Crypto Oracle AI stopped")


# Global application instance
app_instance: Optional[CryptoOracleApp] = None


# FastAPI application for health checks
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager"""
    global app_instance
    
    # Startup
    logger.info("Starting up Crypto Oracle AI...")
    app_instance = CryptoOracleApp()
    await app_instance.initialize()
    
    # Start the main application in a background task
    asyncio.create_task(app_instance.run())
    
    yield
    
    # Shutdown
    if app_instance:
        await app_instance.stop()


# Create FastAPI app
app = FastAPI(
    title="Crypto Oracle AI",
    description="Decentralized Pump/Dump Detection System",
    version="2.0.0",
    lifespan=lifespan
)

# Include UI router
app.include_router(ui_router, prefix="/dashboard")

# Mount static files (only if directory exists)
import os
if os.path.exists("/app/ui/static"):
    app.mount("/static", StaticFiles(directory="/app/ui/static"), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for cloud deployment"""
    return {
        "status": "running",
        "timestamp": asyncio.get_event_loop().time()
    }


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Crypto Oracle AI",
        "version": "2.0.0",
        "description": "Decentralized Pump/Dump Detection System with Enterprise Security",
        "endpoints": {
            "/health": "Health check endpoint",
            "/dashboard": "Real-time monitoring dashboard",
            "/docs": "API documentation (Swagger UI)"
        }
    }


def main():
    """Main entry point"""
    settings = get_settings()
    
    logger.info("Starting Crypto Oracle AI server...")
    logger.info(f"Health check port: {settings.health_check_port}")
    
    # Run FastAPI with uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.health_check_port,
        log_level=settings.log_level.lower()
    )


if __name__ == "__main__":
    main()
