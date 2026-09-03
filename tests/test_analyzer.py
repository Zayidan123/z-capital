"""
Tests for the analyzer module (DeepDiveAnalyzer)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.analyzer import DeepDiveAnalyzer


@pytest.fixture
def analyzer():
    """Analyzer dengan DB mock dan http client yang di-inject"""
    a = DeepDiveAnalyzer(db=MagicMock())
    a.http_client = MagicMock()
    return a


class TestDeepDiveAnalyzer:
    """Test analyzer operations"""

    def test_analyzer_initialization(self, analyzer):
        """Test analyzer can be initialized"""
        assert analyzer is not None
        assert analyzer.smart_wallets == []

    @pytest.mark.asyncio
    async def test_analyze_anomaly_without_api_keys(self, analyzer):
        """Tanpa API key, analisis tetap berjalan dengan confidence dari volume saja"""
        analyzer.settings.etherscan_api_key = None
        analyzer.settings.cryptopanic_api_key = None

        result = await analyzer.analyze_anomaly({
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "volume_spike": 450.0,
        })

        assert isinstance(result, dict)
        assert result["symbol"] == "BTCUSDT"
        assert "confirmed" in result
        assert "confidence_score" in result
        assert any("Volume" in r for r in result["reasons"])

    @pytest.mark.asyncio
    async def test_analyze_anomaly_confirmed_with_smart_money(self, analyzer):
        """Smart money terdeteksi + volume spike -> signal confirmed"""
        analyzer.settings.etherscan_api_key = "test_key"
        analyzer.settings.cryptopanic_api_key = None
        analyzer._check_etherscan = AsyncMock(return_value={
            "type": "etherscan",
            "smart_money_found": True,
            "transactions": [{"wallet": "0xabc", "tx_hash": "0x123"}],
            "checked_wallets": 1,
        })

        result = await analyzer.analyze_anomaly({
            "symbol": "ETHUSDT",
            "price": 3000.0,
            "volume_spike": 500.0,
        })

        assert result["smart_money_detected"] is True
        assert result["confirmed"] is True
        assert result["confidence_score"] >= 0.7

    @pytest.mark.asyncio
    async def test_get_token_address_mapping(self, analyzer):
        """Test mapping symbol ke contract address"""
        assert await analyzer._get_token_address("ETHUSDT") is not None
        assert await analyzer._get_token_address("WBTCUSDT") is None  # tidak ada di mapping
        eth = await analyzer._get_token_address("ETHUSDT")
        assert eth.startswith("0x")

    def test_is_buy_transaction(self, analyzer):
        """Test deteksi buy transaction sederhana"""
        wallet = "0xAbC123"
        tx_to_wallet = {"to": wallet.lower()}
        tx_from_wallet = {"to": "0xother"}

        assert analyzer._is_buy_transaction(tx_to_wallet, wallet) is True
        assert analyzer._is_buy_transaction(tx_from_wallet, wallet) is False
