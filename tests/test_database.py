"""
Tests for the database module
"""
import pytest
import asyncio
from app.database import Database, get_db


class TestDatabase:
    """Test database operations"""
    
    @pytest.mark.asyncio
    async def test_database_connection(self):
        """Test database can connect"""
        db = await get_db()
        assert db is not None
        await db.close()
    
    @pytest.mark.asyncio
    async def test_create_tables(self):
        """Test table creation"""
        db = await get_db()
        await db.create_tables()
        # If no exception raised, tables created successfully
        await db.close()
    
    @pytest.mark.asyncio
    async def test_log_anomaly(self):
        """Test logging anomaly to database"""
        db = await get_db()
        await db.create_tables()
        
        anomaly_id = await db.log_anomaly(
            symbol="BTCUSDT",
            price=50000.0,
            volume_spike=350.0
        )
        
        assert anomaly_id is not None
        assert anomaly_id > 0
        await db.close()
    
    @pytest.mark.asyncio
    async def test_add_smart_wallet(self):
        """Test adding smart wallet"""
        db = await get_db()
        await db.create_tables()
        
        wallet_id = await db.add_smart_wallet(
            address="0x1234567890abcdef1234567890abcdef12345678",
            chain="ethereum",
            win_rate=75.5
        )
        
        assert wallet_id is not None
        await db.close()
    
    @pytest.mark.asyncio
    async def test_log_signal(self):
        """Test logging signal to database"""
        db = await get_db()
        await db.create_tables()
        
        signal_id = await db.log_signal(
            symbol="ETHUSDT",
            signal_type="PUMP",
            message="Test signal",
            status="sent"
        )
        
        assert signal_id is not None
        assert signal_id > 0
        await db.close()
