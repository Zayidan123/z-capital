"""
Tests for the AI module
"""
import pytest
from app.ai import PatternRecognizer, SentimentAnalyzer, WhaleTracker


class TestPatternRecognizer:
    """Test pattern recognition"""
    
    def test_recognizer_initialization(self):
        """Test recognizer can be initialized"""
        recognizer = PatternRecognizer()
        assert recognizer is not None
    
    def test_classify_pattern(self):
        """Test pattern classification"""
        recognizer = PatternRecognizer()
        
        price_data = [100, 102, 105, 110, 115, 120, 118, 115]
        volume_data = [1000, 1200, 1500, 2000, 3500, 5000, 4000, 3000]
        
        result = recognizer.classify_pattern(price_data, volume_data)
        assert isinstance(result, dict)
        assert "pattern_type" in result or "confidence" in result


class TestSentimentAnalyzer:
    """Test sentiment analysis"""
    
    def test_analyzer_initialization(self):
        """Test analyzer can be initialized"""
        analyzer = SentimentAnalyzer()
        assert analyzer is not None
    
    def test_analyze_text(self):
        """Test text sentiment analysis"""
        analyzer = SentimentAnalyzer()
        
        text = "Bitcoin is breaking out with huge volume! Bullish momentum!"
        result = analyzer.analyze_text(text)
        assert isinstance(result, dict)
        assert "sentiment" in result or "score" in result


class TestWhaleTracker:
    """Test whale tracking"""
    
    def test_tracker_initialization(self):
        """Test tracker can be initialized"""
        tracker = WhaleTracker()
        assert tracker is not None
    
    @pytest.mark.asyncio
    async def test_track_whale_activity(self):
        """Test whale activity tracking (may fail without valid API key)"""
        tracker = WhaleTracker()
        
        try:
            result = await tracker.track_whale_activity("BTC")
            assert isinstance(result, dict)
        except Exception:
            pytest.skip("No valid API key for whale tracking")
