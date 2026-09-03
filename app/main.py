"""
Main Orchestrator for Crypto Oracle AI
Coordinates all modules and provides health check endpoint
"""
import asyncio
import logging
import os
import sys
import time
from typing import Dict, Optional, Set
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
from app import runtime_settings
from app.ui.routes import (
    router as ui_router,
    broadcast_update,
    get_alert_system,
    set_notifier,
    record_prune_result,
)

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

        # v2.5: pasang notifier ke dashboard routes agar panel Telegram
        # (status + test-send) memakai instance yang benar-benar berjalan.
        set_notifier(self.notifier)

        # v2.6: muat runtime settings tersimpan + terapkan konfigurasi
        # Telegram yang pernah diubah lewat dashboard (best-effort -
        # kegagalan jaringan Telegram TIDAK boleh menggagalkan startup).
        try:
            await runtime_settings.load_overrides(self.db)
            await self._apply_persisted_telegram_config()
        except Exception as e:
            logger.warning(f"Runtime settings restore skipped: {e}")

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

        # v2.4: sambungkan AlertSystem ke pipeline (evaluasi rules + persist
        # history ke DB) dan pasang callback broadcast WS untuk dashboard.
        alert_system = get_alert_system()
        alert_system.set_alert_callback(self._broadcast_alert)
        logger.info("Alert system wired to anomaly pipeline")

        logger.info("All components initialized successfully")

    async def _apply_persisted_telegram_config(self) -> None:
        """Terapkan konfigurasi Telegram tersimpan (v2.6) ke notifier.

        - chat_id tersimpan selalu dipasang (tidak butuh jaringan).
        - token tersimpan: coba reconfigure (validasi get_me) - bila
          Telegram tidak terjangkau saat startup, konfigurasi env tetap
          dipakai dan percobaan ulang bisa dilakukan lewat dashboard.
        """
        if not self.notifier:
            return
        token = runtime_settings.get_string("telegram_bot_token")
        chat_id = runtime_settings.get_string("telegram_chat_id")
        if chat_id and not self.notifier.chat_id:
            self.notifier.chat_id = str(chat_id)
            logger.info("Telegram chat_id restored from runtime settings")
        if token and chat_id:
            try:
                result = await self.notifier.reconfigure(token=token, chat_id=chat_id)
                if result.get("ok"):
                    logger.info("Telegram bot restored from persisted settings")
                else:
                    logger.warning(
                        "Persisted telegram token invalid/unreachable; "
                        "keeping environment configuration"
                    )
            except Exception as e:
                logger.warning(f"Telegram reconfigure at startup failed: {e}")

    def _spawn_background_task(self, coro) -> asyncio.Task:
        """Create a background task and keep a strong reference to it.

        Referensi kuat diperlukan agar task tidak di-garbage-collect
        sebelum selesai (lihat dokumentasi asyncio.create_task).
        """
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _broadcast_alert(self, alert: Dict) -> None:
        """Callback AlertSystem: dorong alert ter-trigger ke dashboard via WS."""
        try:
            await broadcast_update({
                "type": "alert_triggered",
                "timestamp": _utc_now().isoformat(),
                "data": {
                    "rule": alert.get("rule"),
                    "priority": alert.get("priority"),
                    "symbol": alert.get("symbol"),
                    "channels": alert.get("channels", []),
                    "timestamp": alert.get("timestamp"),
                    "volume_spike": alert.get("data", {}).get("volume_spike"),
                    "confidence_score": alert.get("data", {}).get("confidence_score"),
                    "price": alert.get("data", {}).get("price"),
                },
            })
        except Exception as e:
            logger.warning(f"Failed to broadcast alert: {e}")

    # ===== v2.5: Retensi alert_history (housekeeping otomatis) =====

    async def _prune_alert_history_once(self) -> Optional[int]:
        """Jalankan satu siklus prune alert_history sesuai konfigurasi.

        v2.6: baca override runtime dulu (dashboard), fallback ke env.

        Returns:
            Jumlah baris terhapus, None bila auto-prune dimatikan (0 hari).
        """
        env_days = int(self.settings.alert_history_retention_days or 0)
        days = runtime_settings.get_int("alert_history_retention_days", env_days)
        if days <= 0:
            return None
        deleted = await self.db.prune_alert_history(days)
        record_prune_result(_utc_now().isoformat(), deleted)
        if deleted:
            logger.info(f"Alert retention: pruned {deleted} rows (>{days} days old)")
        return deleted

    async def _alert_retention_loop(self, interval_minutes: int = 60) -> None:
        """Loop background: prune alert_history secara periodik.

        Interval minimum efektif 1 menit agar konfigurasi salah tidak
        menyebabkan spin-loop. Error prune dicatat lalu dicoba lagi
        pada siklus berikutnya (loop tidak pernah mati karena error DB).
        """
        interval = max(1, int(interval_minutes or 1)) * 60
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._prune_alert_history_once()
                except Exception as e:
                    logger.warning(f"Alert retention prune failed: {e}")
        except asyncio.CancelledError:
            logger.debug("Alert retention loop cancelled")

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

            # v2.4: evaluasi alert rules terhadap hasil analisis. Trigger
            # di-persist ke DB + di-broadcast ke dashboard via callback.
            try:
                alert_system = get_alert_system()
                triggered = await alert_system.check_alerts(analysis_result)
                if triggered:
                    logger.info(
                        f"{len(triggered)} alert(s) triggered for {symbol}: "
                        f"{[a['rule'] for a in triggered]}"
                    )
            except Exception as alert_err:
                logger.warning(f"Alert evaluation failed: {alert_err}")

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

    # v2.5: housekeeping alert_history - hapus baris lebih tua dari
    # alert_history_retention_days secara periodik (0 hari = off)
    app_instance._spawn_background_task(
        app_instance._alert_retention_loop(
            app_instance.settings.alert_retention_interval_minutes
        )
    )

    yield

    # Shutdown
    if app_instance:
        await app_instance.stop()


# Create FastAPI app
app = FastAPI(
    title="Crypto Oracle AI",
    description="Decentralized Pump/Dump Detection System",
    version="2.6.0",
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
        "version": "2.6.0",
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
