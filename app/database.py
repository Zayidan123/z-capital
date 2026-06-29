"""
Database module for Crypto Oracle AI
Handles async PostgreSQL connections and operations
"""
import asyncio
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


# Global database instance
db = Database()


async def get_database() -> Database:
    """Get the global database instance"""
    if not db._initialized:
        await db.connect()
    return db
