"""
Tests for the AI module (PatternRecognizer, SentimentAnalyzer, WhaleTracker)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.ai import PatternRecognizer, SentimentAnalyzer, WhaleTracker


@pytest.fixture
def recognizer():
    return PatternRecognizer(db=MagicMock())


@pytest.fixture
def sentiment():
    return SentimentAnalyzer(db=MagicMock())


@pytest.fixture
def whale_tracker():
    tracker = WhaleTracker(db=MagicMock())
    tracker.http_client = MagicMock()
    return tracker


class TestPatternRecognizer:
    """Test pattern recognition"""

    def test_recognizer_initialization(self, recognizer):
        """Test recognizer can be initialized"""
        assert recognizer is not None
        assert len(recognizer.pattern_templates) == 4

    def test_update_price_data(self, recognizer):
        """Test price history update"""
        recognizer.update_price_data("BTCUSDT", price=50000.0, volume=100.0)
        recognizer.update_price_data("BTCUSDT", price=50100.0, volume=150.0)
        assert len(recognizer.price_history["BTCUSDT"]) == 2
        assert len(recognizer.volume_history["BTCUSDT"]) == 2

    @pytest.mark.asyncio
    async def test_recognize_pattern_insufficient_data(self, recognizer):
        """Data kurang dari 10 titik -> hasil default"""
        result = await recognizer.recognize_pattern("BTCUSDT")
        assert isinstance(result, dict)
        assert result["detected_patterns"] == []
        assert result["current_phase"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_recognize_pattern_pump_phase(self, recognizer):
        """Simulasi pump: harga & volume naik tajam -> PUMP_IN_PROGRESS"""
        price, volume = 100.0, 1000.0
        for i in range(20):
            recognizer.update_price_data("PUMPUSDT", price=price, volume=volume)
            price *= 1.3   # +30% per tick -> mean pct_change > 20%
            volume *= 3.5  # +250% per tick -> mean volume_change > 200%
        result = await recognizer.recognize_pattern("PUMPUSDT")
        assert result["current_phase"] == "PUMP_IN_PROGRESS"
        assert result["risk_level"] == "HIGH"


class TestSentimentAnalyzer:
    """Test sentiment analysis"""

    def test_analyzer_initialization(self, sentiment):
        assert sentiment is not None

    @pytest.mark.asyncio
    async def test_analyze_text_positive(self, sentiment):
        """Teks bullish -> sentiment positif"""
        result = await sentiment.analyze_sentiment(
            "BTC", ["Bitcoin is breaking out with huge volume! Bullish momentum! Moon!"]
        )
        assert isinstance(result, dict)
        assert result["overall_sentiment"] == "positive"
        assert result["sentiment_score"] > 0
        assert result["sources_analyzed"] == 1

    @pytest.mark.asyncio
    async def test_analyze_text_negative(self, sentiment):
        """Teks bearish -> sentiment negatif"""
        result = await sentiment.analyze_sentiment(
            "BTC", ["Exchange hack! Crash incoming, scam warning!"]
        )
        assert result["overall_sentiment"] == "negative"
        assert result["sentiment_score"] < 0

    @pytest.mark.asyncio
    async def test_analyze_empty_sources_no_crash(self, sentiment):
        """Bug lama: semua source kosong menyebabkan UnboundLocalError"""
        result = await sentiment.analyze_sentiment("BTC", ["", "", None])
        assert result["sources_analyzed"] == 0
        assert result["overall_sentiment"] == "neutral"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_analyze_multiple_sources_counts_correctly(self, sentiment):
        """Counter sources_analyzed harus akurat (bug lama: selalu 1)"""
        texts = ["moon pump", "hack crash", "report update", "rally adoption"]
        result = await sentiment.analyze_sentiment("BTC", texts)
        assert result["sources_analyzed"] == 4


class TestWhaleTracker:
    """Test whale tracking"""

    def test_tracker_initialization(self, whale_tracker):
        assert whale_tracker is not None
        assert whale_tracker.whale_threshold == 100000

    @pytest.mark.asyncio
    async def test_load_known_whales(self, whale_tracker):
        """Load wallet dari DB ke set whales"""
        whale_tracker.db.get_smart_wallets = AsyncMock(return_value=[
            {"address": "0xabc", "chain": "ETH", "win_rate": 80},
            {"address": "0xdef", "chain": "ETH", "win_rate": 90},
        ])
        await whale_tracker._load_known_whales()
        assert "0xabc" in whale_tracker.whale_wallets
        assert "0xdef" in whale_tracker.whale_wallets

    def test_estimate_value_usd(self, whale_tracker):
        """Estimasi nilai USD dari raw token amount (18 decimals)"""
        value = whale_tracker._estimate_value_usd(str(2 * 10**18), "ETH")
        assert value == 4000.0  # 2 ETH * $2000

    def test_estimate_value_usd_invalid(self, whale_tracker):
        """Input invalid -> 0.0, bukan crash"""
        assert whale_tracker._estimate_value_usd("not-a-number", "ETH") == 0.0
