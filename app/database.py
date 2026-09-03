"""
Database module for Crypto Oracle AI
Handles async PostgreSQL connections and operations
"""
import asyncio
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

import asyncpg
from app.config import get_settings

logger = logging.getLogger(__name__)


class Database:
    """Async PostgreSQL database handler"""
    
    def __init__(self):
        self.settings = get_settings()
        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False
    
    async def connect(self) -> None:
        """Initialize database connection pool"""
        if self._initialized:
            return
        
        try:
            self.pool = await asyncpg.create_pool(
                dsn=self.settings.database_url,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            
            # Create tables if they don't exist
            await self._create_tables()
            
            self._initialized = True
            logger.info("Database connection pool initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            self.pool = None
            self._initialized = False
            logger.info("Database connection pool closed")
    
    async def _create_tables(self) -> None:
        """Create required database tables"""
        async with self.pool.acquire() as conn:
            # Create anomali_logs table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS anomali_logs (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) NOT NULL,
                    price DECIMAL(20, 8) NOT NULL,
                    volume_spike DECIMAL(10, 2) NOT NULL,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    volume_current DECIMAL(20, 8),
                    volume_avg DECIMAL(20, 8),
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create smart_wallets table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_wallets (
                    id SERIAL PRIMARY KEY,
                    address VARCHAR(42) UNIQUE NOT NULL,
                    chain VARCHAR(20) DEFAULT 'ETH',
                    win_rate DECIMAL(5, 2) DEFAULT 0.00,
                    total_trades INTEGER DEFAULT 0,
                    successful_trades INTEGER DEFAULT 0,
                    last_active TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create signals_sent table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signals_sent (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) NOT NULL,
                    signal_type VARCHAR(50) NOT NULL,
                    message TEXT NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    telegram_message_id INTEGER,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create alert_rules table (v2.4: persistensi threshold rules agar
            # perubahan lewat dashboard survive restart)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_rules (
                    name VARCHAR(100) PRIMARY KEY,
                    threshold DOUBLE PRECISION NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create alert_history table (v2.4: riwayat alert yang ter-trigger,
            # tahan restart - sebelumnya hanya in-memory)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id SERIAL PRIMARY KEY,
                    rule VARCHAR(100) NOT NULL,
                    priority VARCHAR(20) NOT NULL,
                    symbol VARCHAR(50) NOT NULL,
                    data JSONB,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create app_settings table (v2.6: runtime settings yang tahan
            # restart - retention days, refresh interval, telegram config)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create webhook_deliveries table (v2.9: log hasil pengiriman
            # webhook - audit delivery, retry terlihat, tahan restart)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id SERIAL PRIMARY KEY,
                    event VARCHAR(20) NOT NULL,
                    ok BOOLEAN NOT NULL,
                    status_code INTEGER,
                    reason VARCHAR(100),
                    attempts INTEGER NOT NULL DEFAULT 1,
                    duration_ms INTEGER,
                    rule VARCHAR(100),
                    symbol VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create webhook_outbox table (v2.10: antrean delivery gagal
            # total - replay manual/otomatis, tahan restart)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_outbox (
                    id SERIAL PRIMARY KEY,
                    payload JSONB NOT NULL,
                    rule VARCHAR(100),
                    symbol VARCHAR(50),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_reason VARCHAR(100),
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    last_attempt_at TIMESTAMPTZ
                )
            """)

            # Create index for the outbox (oldest-first replay scan)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_webhook_outbox_created
                ON webhook_outbox(created_at)
            """)

            # Create indexes for better query performance
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_anomali_logs_symbol 
                ON anomali_logs(symbol)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_anomali_logs_timestamp 
                ON anomali_logs(timestamp)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_sent_symbol 
                ON signals_sent(symbol)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_sent_timestamp 
                ON signals_sent(timestamp)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_history_timestamp 
                ON alert_history(timestamp)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_history_symbol 
                ON alert_history(symbol)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created 
                ON webhook_deliveries(created_at)
            """)
            
            logger.info("Database tables created successfully")
    
    @asynccontextmanager
    async def get_connection(self):
        """Get a database connection from the pool"""
        if not self._initialized:
            await self.connect()
        
        conn = await self.pool.acquire()
        try:
            yield conn
        finally:
            await self.pool.release(conn)
    
    async def log_anomaly(
        self,
        symbol: str,
        price: float,
        volume_spike: float,
        volume_current: float,
        volume_avg: float
    ) -> int:
        """Log a volume anomaly to the database"""
        async with self.get_connection() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO anomali_logs (symbol, price, volume_spike, volume_current, volume_avg)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                symbol, price, volume_spike, volume_current, volume_avg
            )
            logger.info(f"Logged anomaly for {symbol}: {volume_spike}% spike")
            return result['id']
    
    async def add_smart_wallet(
        self,
        address: str,
        chain: str = 'ETH',
        win_rate: float = 0.0,
        total_trades: int = 0,
        successful_trades: int = 0
    ) -> None:
        """Add or update a smart wallet in the database"""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO smart_wallets (address, chain, win_rate, total_trades, successful_trades, last_active)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (address) DO UPDATE SET
                    win_rate = EXCLUDED.win_rate,
                    total_trades = EXCLUDED.total_trades,
                    successful_trades = EXCLUDED.successful_trades,
                    last_active = CURRENT_TIMESTAMP
                """,
                address, chain, win_rate, total_trades, successful_trades
            )
    
    async def get_smart_wallets(self) -> List[Dict[str, Any]]:
        """Get all smart wallets from the database"""
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                "SELECT address, chain, win_rate FROM smart_wallets WHERE win_rate > 50"
            )
            return [dict(row) for row in rows]
    
    async def log_signal(
        self,
        symbol: str,
        signal_type: str,
        message: str,
        status: str = 'pending',
        telegram_message_id: Optional[int] = None
    ) -> int:
        """Log a sent signal to the database"""
        async with self.get_connection() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO signals_sent (symbol, signal_type, message, status, telegram_message_id)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                symbol, signal_type, message, status, telegram_message_id
            )
            logger.info(f"Logged signal for {symbol}: {signal_type}")
            return result['id']
    
    async def update_signal_status(self, signal_id: int, status: str) -> None:
        """Update the status of a signal"""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE signals_sent SET status = $1 WHERE id = $2",
                status, signal_id
            )
    
    async def get_recent_anomalies(
        self,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get recent anomalies from the database"""
        async with self.get_connection() as conn:
            if symbol:
                rows = await conn.fetch(
                    """
                    SELECT * FROM anomali_logs 
                    WHERE symbol = $1 
                    ORDER BY timestamp DESC 
                    LIMIT $2
                    """,
                    symbol, limit
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM anomali_logs 
                    ORDER BY timestamp DESC 
                    LIMIT $1
                    """,
                    limit
                )
            return [dict(row) for row in rows]
    
    async def get_price_history(
        self,
        symbol: str,
        limit: int = 60
    ) -> List[Dict[str, Any]]:
        """Get chronological price history for one symbol (oldest first).

        Dipakai endpoint sparkline: hasilnya di-reverse agar grafik
        bergerak dari kiri (lama) ke kanan (baru).
        """
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT price, volume_spike, timestamp
                FROM anomali_logs
                WHERE symbol = $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                symbol, limit
            )
            # DESC di SQL → reverse menjadi ascending (lama → baru)
            return [dict(row) for row in reversed(rows)]

    async def get_symbol_summary(self) -> List[Dict[str, Any]]:
        """Per-symbol aggregate untuk Market Pulse & filter dropdown.

        Mengembalikan: symbol, anomaly_count, avg_spike, last_price, last_seen,
        diurutkan dari symbol paling aktif.
        """
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    symbol,
                    COUNT(*)::int AS anomaly_count,
                    AVG(volume_spike)::float AS avg_spike,
                    (array_agg(price ORDER BY timestamp DESC))[1]::float AS last_price,
                    MAX(timestamp) AS last_seen
                FROM anomali_logs
                GROUP BY symbol
                ORDER BY anomaly_count DESC, symbol ASC
                """
            )
            return [dict(row) for row in rows]

    # ===== v2.4: Persistensi alert rules & history =====

    async def get_alert_rule_thresholds(self) -> Dict[str, float]:
        """Ambil seluruh threshold rule yang tersimpan di DB.

        Returns:
            Dict {rule_name: threshold}
        """
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                "SELECT name, threshold FROM alert_rules"
            )
            return {row["name"]: float(row["threshold"]) for row in rows}

    async def upsert_alert_rule_threshold(self, name: str, threshold: float) -> None:
        """Simpan/update threshold satu alert rule di DB (survive restart)."""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO alert_rules (name, threshold, updated_at)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (name) DO UPDATE SET
                    threshold = EXCLUDED.threshold,
                    updated_at = CURRENT_TIMESTAMP
                """,
                name, threshold,
            )

    async def log_alert(
        self,
        rule: str,
        priority: str,
        symbol: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Simpan alert yang ter-trigger ke alert_history (persisten)."""
        import json as _json
        async with self.get_connection() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO alert_history (rule, priority, symbol, data)
                VALUES ($1, $2, $3, $4::jsonb)
                RETURNING id
                """,
                rule, priority, symbol,
                _json.dumps(data or {}, default=str),
            )
            return result["id"]

    async def get_alert_history(
        self,
        limit: int = 50,
        symbol: Optional[str] = None,
        hours: Optional[int] = None,
        priority: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Riwayat alert terbaru dari DB (terbaru dulu).

        Kolom data (JSONB) dikonversi ke dict agar siap dikirim sebagai JSON.

        v2.6: filter opsional symbol (exact match) dan hours (jendela waktu
        ke belakang) untuk click-to-filter dari heat map dashboard.
        v2.9: filter opsional priority (exact, high/medium/low).
        """
        import json as _json
        async with self.get_connection() as conn:
            clauses = []
            args: List[Any] = []
            if symbol:
                args.append(str(symbol))
                clauses.append(f"symbol = ${len(args)}")
            if hours is not None and int(hours) > 0:
                args.append(int(hours))
                clauses.append(
                    f"timestamp > NOW() - make_interval(hours => ${len(args)})"
                )
            if priority:
                args.append(str(priority).lower())
                # v2.9: LOWER di sisi kolom - data lama menyimpan "HIGH",
                # data baru "high"; keduanya harus cocok
                clauses.append(f"LOWER(priority) = ${len(args)}")
            args.append(max(1, min(int(limit), 500)))
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = await conn.fetch(
                f"""
                SELECT id, rule, priority, symbol, data, timestamp
                FROM alert_history
                {where}
                ORDER BY timestamp DESC
                LIMIT ${len(args)}
                """,
                *args,
            )
            history: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                raw = item.get("data")
                if isinstance(raw, str):
                    try:
                        item["data"] = _json.loads(raw)
                    except (ValueError, TypeError):
                        item["data"] = None
                history.append(item)
            return history

    # ===== v2.5: Retensi (housekeeping) & agregasi alert =====

    async def prune_alert_history(self, retention_days: int) -> int:
        """Hapus alert_history lebih tua dari `retention_days` hari.

        Returns:
            Jumlah baris yang terhapus. 0 jika retention_days <= 0
            (tidak menjalankan DELETE sama sekali).
        """
        days = int(retention_days)
        if days <= 0:
            return 0
        async with self.get_connection() as conn:
            status = await conn.execute(
                """
                DELETE FROM alert_history
                WHERE timestamp < NOW() - make_interval(days => $1)
                """,
                days,
            )
            # asyncpg execute() mengembalikan tag status, mis. "DELETE 12"
            if isinstance(status, str) and status.startswith("DELETE"):
                try:
                    return int(status.split()[-1])
                except (ValueError, IndexError):
                    return 0
            return 0

    async def get_alert_heatmap(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Agregasi alert per-symbol per-jam untuk heat map dashboard.

        Args:
            hours: jendela waktu berapa jam ke belakang.

        Returns:
            List baris {symbol, hour, count, max_priority} diurutkan
            per symbol lalu per jam.
        """
        window = max(1, min(int(hours), 720))
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    symbol,
                    date_trunc('hour', timestamp) AS hour,
                    COUNT(*)::int AS count,
                    MAX(CASE priority
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 1
                        ELSE 0 END)::int AS severity
                FROM alert_history
                WHERE timestamp > NOW() - make_interval(hours => $1)
                GROUP BY symbol, date_trunc('hour', timestamp)
                ORDER BY symbol ASC, hour ASC
                """,
                window,
            )
            return [dict(row) for row in rows]

    async def get_alert_rule_stats(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Agregasi alert per-rule per-jam untuk audit sparkline rules panel (v2.7).

        Mirip get_alert_heatmap tetapi dikelompokkan berdasarkan `rule`
        alih-alih `symbol`. Hasil bersifat sparse (hanya jam yang punya
        alert); endpoint yang memakai method ini yang mengisi slot jam
        kosong dengan count 0 agar mudah digambar frontend.

        Args:
            hours: jendela waktu berapa jam ke belakang.

        Returns:
            List baris {rule, hour, count, max_priority} terurut per rule
            lalu per jam.
        """
        window = max(1, min(int(hours), 720))
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    rule,
                    date_trunc('hour', timestamp) AS hour,
                    COUNT(*)::int AS count,
                    MAX(CASE priority
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 1
                        ELSE 0 END)::int AS severity
                FROM alert_history
                WHERE timestamp > NOW() - make_interval(hours => $1)
                GROUP BY rule, date_trunc('hour', timestamp)
                ORDER BY rule ASC, hour ASC
                """,
                window,
            )
            return [dict(row) for row in rows]

    async def get_alert_rule_stats_daily(self, days: int = 7) -> List[Dict[str, Any]]:
        """Agregasi alert per-rule per-HARI (v2.10, audit 7-hari).

        Melengkapi get_alert_rule_stats (per-jam): jendela seminggu
        menghasilkan 168 bucket jam terlalu padat untuk sparkline, jadi
        dikelompokkan per hari. Sifatnya sparse seperti saudaranya;
        endpoint yang memakai method ini yang mengisi slot hari kosong.
        """
        window = max(1, min(int(days), 30))
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    rule,
                    date_trunc('day', timestamp) AS day,
                    COUNT(*)::int AS count,
                    MAX(CASE priority
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 1
                        ELSE 0 END)::int AS severity
                FROM alert_history
                WHERE timestamp > NOW() - make_interval(days => $1)
                GROUP BY rule, date_trunc('day', timestamp)
                ORDER BY rule ASC, day ASC
                """,
                window,
            )
            return [dict(row) for row in rows]

    async def get_alert_history_stats(self) -> Dict[str, Any]:
        """Statistik tabel alert_history untuk panel retensi dashboard."""
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS total_alerts,
                       MIN(timestamp) AS oldest_alert
                FROM alert_history
                """
            )
            return dict(row) if row else {"total_alerts": 0, "oldest_alert": None}

    # ===== v2.6: Runtime settings (key-value store, tahan restart) =====

    async def get_app_settings(self, keys: Optional[List[str]] = None) -> Dict[str, str]:
        """Ambil runtime settings dari DB.

        Args:
            keys: filter opsional; None berarti ambil semua.

        Returns:
            Dict {key: value_str}. Kosong bila tabel belum ada / DB gagal
            (dipanggil via try/except di pemanggil).
        """
        async with self.get_connection() as conn:
            if keys:
                rows = await conn.fetch(
                    "SELECT key, value FROM app_settings WHERE key = ANY($1)",
                    list(keys),
                )
            else:
                rows = await conn.fetch("SELECT key, value FROM app_settings")
            return {row["key"]: row["value"] for row in rows}

    async def set_app_setting(self, key: str, value: str) -> None:
        """Simpan/update satu runtime setting di DB (survive restart)."""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ($1, $2, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                str(key), str(value),
            )

    async def delete_app_setting(self, key: str) -> bool:
        """Hapus satu runtime setting. True bila ada baris terhapus."""
        async with self.get_connection() as conn:
            status = await conn.execute(
                "DELETE FROM app_settings WHERE key = $1", str(key)
            )
            return isinstance(status, str) and status.startswith("DELETE") \
                and not status.endswith(" 0")

    # ===== v2.9: Webhook delivery log (audit delivery tahan restart) =====

    async def log_webhook_delivery(
        self,
        event: str,
        ok: bool,
        status_code: Optional[int] = None,
        reason: Optional[str] = None,
        attempts: int = 1,
        duration_ms: Optional[int] = None,
        rule: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> int:
        """Catat satu hasil pengiriman webhook ke DB (audit + retry log).

        Dipanggil setelah dispatch selesai (test endpoint maupun pipeline
        alert) sehingga riwayat delivery tetap ada meski proses restart.
        Returns id baris yang dibuat.
        """
        async with self.get_connection() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO webhook_deliveries
                    (event, ok, status_code, reason, attempts, duration_ms, rule, symbol)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                str(event)[:20],
                bool(ok),
                int(status_code) if status_code is not None else None,
                (str(reason)[:100] if reason else None),
                max(1, int(attempts or 1)),
                int(duration_ms) if duration_ms is not None else None,
                (str(rule)[:100] if rule else None),
                (str(symbol)[:50] if symbol else None),
            )
            return result["id"]

    async def get_webhook_deliveries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Delivery webhook terbaru (terbaru dulu), dibatasi 1..200."""
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, event, ok, status_code, reason, attempts,
                       duration_ms, rule, symbol, created_at
                FROM webhook_deliveries
                ORDER BY created_at DESC, id DESC
                LIMIT $1
                """,
                max(1, min(int(limit), 200)),
            )
            return [dict(row) for row in rows]

    async def prune_webhook_deliveries(self, retention_days: int) -> int:
        """Hapus delivery log lebih tua dari N hari (0 = tidak menghapus)."""
        days = int(retention_days)
        if days <= 0:
            return 0
        async with self.get_connection() as conn:
            status = await conn.execute(
                """
                DELETE FROM webhook_deliveries
                WHERE created_at < NOW() - make_interval(days => $1)
                """,
                days,
            )
            if isinstance(status, str) and status.startswith("DELETE"):
                try:
                    return int(status.split()[-1])
                except (ValueError, IndexError):
                    return 0
            return 0

    # ===== v2.10: Webhook outbox (antrean delivery gagal total) =====

    async def enqueue_webhook_outbox(
        self,
        payload: Dict[str, Any],
        rule: Optional[str] = None,
        symbol: Optional[str] = None,
        attempts: int = 0,
        last_reason: Optional[str] = None,
    ) -> Optional[int]:
        """Simpan alert yang gagal terkirim ke outbox (replay nanti).

        Dipanggil best-effort oleh pemanggil: bila DB gagal, alert tetap
        sudah disiarkan dan pipeline utama tidak boleh terpengaruh.
        Returns id baris baru, atau None bila gagal.
        """
        try:
            async with self.get_connection() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO webhook_outbox
                        (payload, rule, symbol, attempts, last_reason)
                    VALUES ($1::jsonb, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    json.dumps(payload, default=str),
                    (str(rule)[:100] if rule else None),
                    (str(symbol)[:50] if symbol else None),
                    max(0, int(attempts or 0)),
                    (str(last_reason)[:100] if last_reason else None),
                )
                return row["id"] if row else None
        except Exception as e:  # noqa: BLE001 - outbox tidak boleh raise di pipeline
            logger.debug(f"Webhook outbox enqueue failed: {e}")
            return None

    async def get_webhook_outbox(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Ambil antrean outbox (tertua dulu - urutan replay adil)."""
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, payload, rule, symbol, attempts, last_reason,
                       created_at, last_attempt_at
                FROM webhook_outbox
                ORDER BY created_at ASC, id ASC
                LIMIT $1
                """,
                max(1, min(int(limit), 200)),
            )
            return [dict(row) for row in rows]

    async def count_webhook_outbox(self) -> int:
        """Jumlah alert yang masih menunggu replay."""
        async with self.get_connection() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM webhook_outbox") or 0)

    async def delete_webhook_outbox(self, ids: List[int]) -> int:
        """Hapus antrean yang sudah berhasil direplay. Returns jumlah hapus."""
        clean = [int(i) for i in ids if i is not None]
        if not clean:
            return 0
        async with self.get_connection() as conn:
            status = await conn.execute(
                "DELETE FROM webhook_outbox WHERE id = ANY($1)", clean
            )
            if isinstance(status, str) and status.startswith("DELETE"):
                try:
                    return int(status.split()[-1])
                except (ValueError, IndexError):
                    return 0
            return 0

    async def record_outbox_attempt(self, ids: List[int], reason: Optional[str] = None) -> None:
        """Catat bahwa sekumpulan antrean baru saja dicoba replay lagi."""
        clean = [int(i) for i in ids if i is not None]
        if not clean:
            return
        async with self.get_connection() as conn:
            await conn.execute(
                """
                UPDATE webhook_outbox
                SET attempts = attempts + 1,
                    last_attempt_at = CURRENT_TIMESTAMP,
                    last_reason = $2
                WHERE id = ANY($1)
                """,
                clean,
                (str(reason)[:100] if reason else None),
            )

    async def prune_webhook_outbox(self, retention_days: int) -> int:
        """Hapus antrean lebih tua dari N hari (0 = tidak menghapus)."""
        days = int(retention_days)
        if days <= 0:
            return 0
        async with self.get_connection() as conn:
            status = await conn.execute(
                """
                DELETE FROM webhook_outbox
                WHERE created_at < NOW() - make_interval(days => $1)
                """,
                days,
            )
            if isinstance(status, str) and status.startswith("DELETE"):
                try:
                    return int(status.split()[-1])
                except (ValueError, IndexError):
                    return 0
            return 0

    # ===== v2.10: Delivery health (agregasi 24h, satu query) =====

    async def get_webhook_health(self, hours: int = 24) -> Dict[str, Any]:
        """Ringkasan kesehatan delivery webhook dalam jendela N jam.

        Satu pass agregasi: total, ok, fail, success rate, rata-rata
        durasi (hanya baris dengan durasi), rata-rata percobaan, alasan
        kegagalan terakhir. Bila tidak ada data, field tetap terisi
        dengan nilai netral agar frontend tidak perlu null-check.
        """
        window = max(1, min(int(hours), 720))
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE ok)::int AS ok,
                       COUNT(*) FILTER (WHERE NOT ok)::int AS fail,
                       AVG(duration_ms)::float AS avg_duration_ms,
                       AVG(attempts)::float AS avg_attempts
                FROM webhook_deliveries
                WHERE created_at > NOW() - make_interval(hours => $1)
                """,
                window,
            )
            last_fail = await conn.fetchval(
                """
                SELECT reason FROM webhook_deliveries
                WHERE NOT ok AND created_at > NOW() - make_interval(hours => $1)
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                window,
            )
        d = dict(row) if row else {}
        total = int(d.get("total") or 0)
        ok_count = int(d.get("ok") or 0)
        avg_dur = d.get("avg_duration_ms")
        avg_att = d.get("avg_attempts")
        return {
            "window_hours": window,
            "total": total,
            "ok": ok_count,
            "fail": int(d.get("fail") or 0),
            "success_rate": round(ok_count / total * 100, 1) if total else None,
            "avg_duration_ms": int(avg_dur) if avg_dur is not None else None,
            "avg_attempts": round(float(avg_att), 2) if avg_att is not None else None,
            "last_fail_reason": last_fail,
        }

    async def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent signals from the database"""
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM signals_sent 
                ORDER BY timestamp DESC 
                LIMIT $1
                """,
                limit
            )
            return [dict(row) for row in rows]
    
    async def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        async with self.get_connection() as conn:
            # Count total signals
            total_signals = await conn.fetchval("SELECT COUNT(*) FROM signals_sent")
            
            # Count signals in last 24h
            signals_24h = await conn.fetchval(
                "SELECT COUNT(*) FROM signals_sent WHERE timestamp > NOW() - INTERVAL '24 hours'"
            )
            
            # Count anomalies
            total_anomalies = await conn.fetchval("SELECT COUNT(*) FROM anomali_logs")
            
            # Count smart wallets
            smart_wallets = await conn.fetchval("SELECT COUNT(*) FROM smart_wallets")
            
            # Calculate success rate (mock calculation based on status)
            success_count = await conn.fetchval(
                "SELECT COUNT(*) FROM signals_sent WHERE status = 'sent'"
            )
            success_rate = round((success_count / total_signals * 100), 2) if total_signals > 0 else 0
            
            return {
                "total_signals": total_signals,
                "signals_24h": signals_24h,
                "total_anomalies": total_anomalies,
                "smart_wallets_count": smart_wallets,
                "success_rate": success_rate,
                "uptime_hours": 0  # Will be calculated in main.py
            }


# Global database instance
db = Database()


async def get_database() -> Database:
    """Get the global database instance"""
    if not db._initialized:
        await db.connect()
    return db


async def get_recent_signals(limit: int = 50) -> List[Dict[str, Any]]:
    """Helper function to get recent signals"""
    return await db.get_recent_signals(limit)


async def get_system_stats() -> Dict[str, Any]:
    """Helper function to get system stats"""
    return await db.get_system_stats()
