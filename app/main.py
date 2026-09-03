"""
Main Orchestrator for Crypto Oracle AI
Coordinates all modules and provides health check endpoint
"""
import asyncio
import logging
import os
import sys
import time
from typing import Optional, Set
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.config import get_settings
from app.database import Database, get_database
from app.streamer import BinanceStreamer
from app.analyzer import DeepDiveAnalyzer
from app.notifier import TelegramNotifier
from app.ui.routes import router as ui_router, broadcast_update

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Timezone-aware UTC now (datetime.utcnow() is deprecated in 3.12+)."""
    return datetime.now(timezone.utc)


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
        self.started_at: float = time.monotonic()
        self._background_tasks: Set[asyncio.Task] = set()

    @property
    def uptime_hours(self) -> float:
        """Uptime aplikasi dalam jam"""
        return round((time.monotonic() - self.started_at) / 3600, 2)

    async def _stats_broadcast_loop(self, interval: int = 30) -> None:
        """Broadcast statistik terbaru ke semua dashboard client secara periodik.

        Sebelumnya dashboard hanya refresh via polling HTTP; kini stats juga
        didorong otomatis lewat WebSocket sehingga semua client sinkron.
        """
        from app.ui.routes import get_dashboard_stats

        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    stats = await get_dashboard_stats()
                    await broadcast_update({
                        "type": "stats_update",
                        "timestamp": _utc_now().isoformat(),
                        "data": stats.get("data") if stats.get("status") == "success" else None,
                    })
                except Exception as e:
                    logger.debug(f"Stats broadcast skipped: {e}")
        except asyncio.CancelledError:
            logger.debug("Stats broadcast loop cancelled")

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

    def _spawn_background_task(self, coro) -> asyncio.Task:
        """Create a background task and keep a strong reference to it.

        Referensi kuat diperlukan agar task tidak di-garbage-collect
        sebelum selesai (lihat dokumentasi asyncio.create_task).
        """
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _handle_anomaly(self, anomaly_data: dict) -> None:
        """
        Callback handler for detected anomalies
        Analyzes and sends notifications if confirmed
        """
        try:
            symbol = anomaly_data.get('symbol', 'UNKNOWN')
            logger.info(f"Handling anomaly for {symbol}")

            # Push real-time update ke dashboard (live feed)
            await broadcast_update({
                "type": "anomaly_detected",
                "timestamp": _utc_now().isoformat(),
                "data": anomaly_data,
            })

            # Perform deep analysis
            analysis_result = await self.analyzer.analyze_anomaly(anomaly_data)

            # Add price to analysis result
            analysis_result['price'] = anomaly_data.get('price', 0)
            analysis_result['volume_spike'] = anomaly_data.get('volume_spike', 0)

            # Send notification if signal is confirmed
            if analysis_result.get('confirmed', False):
                logger.info(f"Confirmed signal for {symbol}, sending notification")
                await self.notifier.send_signal(analysis_result)

                # Beri tahu dashboard bahwa sinyal terkonfirmasi
                await broadcast_update({
                    "type": "signal_confirmed",
                    "timestamp": _utc_now().isoformat(),
                    "data": {
                        "symbol": symbol,
                        "price": analysis_result.get('price', 0),
                        "volume_spike": analysis_result.get('volume_spike', 0),
                        "confidence": analysis_result.get('confidence_score', 0),
                    },
                })
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
            try:
                await self.streamer.stop()
            except Exception as e:
                logger.warning(f"Error stopping streamer: {e}")

        # Stop analyzer
        if self.analyzer:
            try:
                await self.analyzer.stop()
            except Exception as e:
                logger.warning(f"Error stopping analyzer: {e}")

        # Stop notifier
        if self.notifier:
            try:
                await self.notifier.stop()
            except Exception as e:
                logger.warning(f"Error stopping notifier: {e}")

        # Close database connections
        if self.db:
            try:
                await self.db.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting database: {e}")

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

    # Start the main application as a tracked background task
    app_instance._spawn_background_task(app_instance.run())

    # Dorong stats terbaru ke dashboard via WebSocket setiap 30 detik
    app_instance._spawn_background_task(app_instance._stats_broadcast_loop(30))

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
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "ui", "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for cloud deployment"""
    loop = asyncio.get_running_loop()
    return {
        "status": "running",
        "timestamp": loop.time()
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
