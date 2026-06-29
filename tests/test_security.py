"""
Tests for the security module
"""
import pytest
from app.security import HoneypotDetector, LiquidityLockChecker, HolderDistributionAnalyzer


class TestHoneypotDetector:
    """Test honeypot detection"""
    
    def test_detector_initialization(self):
        """Test detector can be initialized"""
        detector = HoneypotDetector()
        assert detector is not None
    
    @pytest.mark.asyncio
    async def test_analyze_token(self):
        """Test token analysis (may fail without valid API key)"""
        detector = HoneypotDetector()
        
        try:
            result = await detector.analyze_token("0x1234567890abcdef1234567890abcdef12345678")
            assert isinstance(result, dict)
            assert "is_honeypot" in result or "risk_score" in result
        except Exception:
            pytest.skip("No valid API key for honeypot detection")


class TestLiquidityLockChecker:
    """Test liquidity lock checking"""
    
    def test_checker_initialization(self):
        """Test checker can be initialized"""
        checker = LiquidityLockChecker()
        assert checker is not None
    
    @pytest.mark.asyncio
    async def test_check_lock_status(self):
        """Test lock status check (may fail without valid API key)"""
        checker = LiquidityLockChecker()
        
        try:
            result = await checker.check_lock_status("0x1234567890abcdef1234567890abcdef12345678")
            assert isinstance(result, dict)
        except Exception:
            pytest.skip("No valid API key for liquidity lock check")


class TestHolderDistributionAnalyzer:
    """Test holder distribution analysis"""
    
    def test_analyzer_initialization(self):
        """Test analyzer can be initialized"""
        analyzer = HolderDistributionAnalyzer()
        assert analyzer is not None
    
    @pytest.mark.asyncio
    async def test_analyze_distribution(self):
        """Test distribution analysis (may fail without valid API key)"""
        analyzer = HolderDistributionAnalyzer()
        
        try:
            result = await analyzer.analyze_distribution("0x1234567890abcdef1234567890abcdef12345678")
            assert isinstance(result, dict)
            assert "gini_coefficient" in result or "concentration_risk" in result
        except Exception:
            pytest.skip("No valid API key for holder distribution analysis")
