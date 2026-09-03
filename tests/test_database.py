"""
Tests for the database module (unit tests dengan mock pool - tanpa Postgres riil)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.database import Database


@pytest.fixture
def mock_db():
    """Database instance dengan pool yang di-mock"""
    db = Database()
    db.pool = MagicMock()
    db._initialized = True

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    conn.fetch = AsyncMock(return_value=[{"symbol": "BTCUSDT", "price": 50000}])
    conn.fetchval = AsyncMock(return_value=5)
    conn.execute = AsyncMock()

    # asyncpg pool.acquire() adalah awaitable yang mengembalikan koneksi
    db.pool.acquire = AsyncMock(return_value=conn)
    db.pool.release = AsyncMock()

    db._mock_conn = conn
    return db


class TestDatabase:
    """Test database operations dengan mock"""

    @pytest.mark.asyncio
    async def test_log_anomaly(self, mock_db):
        """Test logging anomaly to database"""
        anomaly_id = await mock_db.log_anomaly(
            symbol="BTCUSDT",
            price=50000.0,
            volume_spike=350.0,
            volume_current=1000.0,
            volume_avg=200.0,
        )
        assert anomaly_id is not None
        assert anomaly_id > 0
        # Verifikasi parameterized query dipanggil
        args = mock_db._mock_conn.fetchrow.call_args[0]
        assert "INSERT INTO anomali_logs" in args[0]
        assert len(args) == 6  # query + 5 params

    @pytest.mark.asyncio
    async def test_add_smart_wallet(self, mock_db):
        """Test adding smart wallet (upsert, returns None)"""
        result = await mock_db.add_smart_wallet(
            address="0x1234567890abcdef1234567890abcdef12345678",
            chain="ETH",
            win_rate=75.5,
        )
        assert result is None  # add_smart_wallet tidak mengembalikan apa pun
        args = mock_db._mock_conn.execute.call_args[0]
        assert "INSERT INTO smart_wallets" in args[0]
        assert "ON CONFLICT" in args[0]

    @pytest.mark.asyncio
    async def test_log_signal(self, mock_db):
        """Test logging signal to database"""
        signal_id = await mock_db.log_signal(
            symbol="ETHUSDT",
            signal_type="PUMP_ALERT",
            message="Test signal",
            status="sent",
        )
        assert signal_id is not None
        assert signal_id > 0

    @pytest.mark.asyncio
    async def test_get_smart_wallets_filters_win_rate(self, mock_db):
        """Test get_smart_wallets hanya ambil wallet dengan win_rate > 50"""
        wallets = await mock_db.get_smart_wallets()
        assert isinstance(wallets, list)
        query = mock_db._mock_conn.fetch.call_args[0][0]
        assert "win_rate > 50" in query

    @pytest.mark.asyncio
    async def test_get_recent_anomalies_with_symbol(self, mock_db):
        """Test get_recent_anomalies dengan filter symbol"""
        anomalies = await mock_db.get_recent_anomalies(symbol="BTCUSDT", limit=10)
        assert isinstance(anomalies, list)
        args = mock_db._mock_conn.fetch.call_args[0]
        assert "WHERE symbol = $1" in args[0]

    @pytest.mark.asyncio
    async def test_get_recent_anomalies_without_symbol(self, mock_db):
        """Test get_recent_anomalies tanpa filter"""
        anomalies = await mock_db.get_recent_anomalies()
        assert isinstance(anomalies, list)
        query = mock_db._mock_conn.fetch.call_args[0][0]
        assert "WHERE" not in query

    @pytest.mark.asyncio
    async def test_get_system_stats(self, mock_db):
        """Test system stats structure"""
        stats = await mock_db.get_system_stats()
        assert "total_signals" in stats
        assert "signals_24h" in stats
        assert "total_anomalies" in stats
        assert "success_rate" in stats
        assert "uptime_hours" in stats

    @pytest.mark.asyncio
    async def test_update_signal_status(self, mock_db):
        """Test update signal status"""
        await mock_db.update_signal_status(1, "sent")
        args = mock_db._mock_conn.execute.call_args[0]
        assert "UPDATE signals_sent" in args[0]

    @pytest.mark.asyncio
    async def test_disconnect_resets_pool(self):
        """Setelah disconnect, pool harus di-reset agar reconnect aman"""
        db = Database()
        mock_pool = AsyncMock()
        db.pool = mock_pool
        db._initialized = True

        await db.disconnect()

        mock_pool.close.assert_awaited_once()
        assert db.pool is None
        assert db._initialized is False
