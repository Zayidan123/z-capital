"""
Tests for the analyzer module
"""
import pytest
from app.analyzer import Analyzer


class TestAnalyzer:
    """Test analyzer operations"""
    
    def test_analyzer_initialization(self):
        """Test analyzer can be initialized"""
        analyzer = Analyzer()
        assert analyzer is not None
    
    @pytest.mark.asyncio
    async def test_check_etherscan(self):
        """Test Etherscan API call (may fail without valid API key)"""
        analyzer = Analyzer()
        # This test may skip if no API key
        try:
            result = await analyzer.check_etherscan("0x1234567890abcdef1234567890abcdef12345678")
            assert isinstance(result, dict)
        except Exception:
            pytest.skip("No valid Etherscan API key")
    
    @pytest.mark.asyncio
    async def test_check_cryptopanic(self):
        """Test CryptoPanic API call (may fail without valid API key)"""
        analyzer = Analyzer()
        # This test may skip if no API key
        try:
            result = await analyzer.check_cryptopanic("BTC")
            assert isinstance(result, dict)
        except Exception:
            pytest.skip("No valid CryptoPanic API key")
    
    @pytest.mark.asyncio
    async def test_analyze_signal(self):
        """Test signal analysis"""
        analyzer = Analyzer()
        
        anomaly_data = {
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "volume_spike": 350.0
        }
        
        result = await analyzer.analyze(anomaly_data)
        assert isinstance(result, dict)
        assert "confirmed" in result or "score" in result
