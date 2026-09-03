"""
Tests for the security module (hardening.py: SignalValidator, PenetrationTester, DependencyAuditor)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.security.hardening import (
    SecretsManager,
    SignalValidator,
    PenetrationTester,
    DependencyAuditor,
)


class TestSecretsManager:
    """Test secrets manager"""

    def test_initialization(self):
        manager = SecretsManager()
        assert manager is not None

    def test_get_secret_from_env(self, monkeypatch):
        monkeypatch.setenv("TEST_SECRET_XYZ", "supersecretvalue123")
        manager = SecretsManager()
        assert manager.get_secret("TEST_SECRET_XYZ") == "supersecretvalue123"

    def test_get_secret_default(self, monkeypatch):
        monkeypatch.delenv("TEST_MISSING_SECRET", raising=False)
        manager = SecretsManager()
        assert manager.get_secret("TEST_MISSING_SECRET", "fallback") == "fallback"

    def test_validate_secret_strength(self):
        manager = SecretsManager()
        assert manager.validate_secret_strength("Str0ng!Secret#Pass") is True
        assert manager.validate_secret_strength("weak") is False
        assert manager.validate_secret_strength("NOUPPERCASE123!") is False
        assert manager.validate_secret_strength("NoDigitHere!!") is False


class TestSignalValidator:
    """Test multi-layer signal validation"""

    @pytest.fixture
    def validator(self):
        return SignalValidator()

    @pytest.mark.asyncio
    async def test_validate_good_signal(self, validator):
        """Sinyal lengkap & bagus -> STRONG_BUY/BUY"""
        result = await validator.validate_signal({
            "symbol": "BTCUSDT",
            "volume_change_percent": 450.0,
            "price_change_percent": 12.0,
            "smart_money_detected": True,
            "smart_wallet_count": 3,
            "sentiment_score": 0.8,
            "news_count": 5,
            "liquidity_locked": True,
            "liquidity_amount": 125000,
            "is_honeypot": False,
            "buy_tax": 5,
            "sell_tax": 8,
        })
        assert result["layers_passed"] == result["total_layers"]
        assert result["confidence_score"] == 100.0
        assert result["recommendation"] in ("STRONG_BUY", "BUY")

    @pytest.mark.asyncio
    async def test_validate_empty_signal_rejected(self, validator):
        """Sinyal kosong -> REJECT"""
        result = await validator.validate_signal({"symbol": "FAKEUSDT"})
        assert result["recommendation"] == "REJECT"
        assert result["layers_passed"] == 0

    @pytest.mark.asyncio
    async def test_validation_layers_structure(self, validator):
        """Setiap layer punya struktur yang konsisten"""
        result = await validator.validate_signal({"symbol": "TESTUSDT"})
        for detail in result["details"]:
            assert "layer" in detail
            assert "passed" in detail
            assert "weight" in detail
            assert "reason" in detail


class TestPenetrationTester:
    """Test penetration test simulation"""

    @pytest.mark.asyncio
    async def test_run_security_tests_no_crash(self):
        """Bug lama: AttributeError pada settings.TELEGRAM_BOT_TOKEN / REDIS_HOST"""
        tester = PenetrationTester()
        results = await tester.run_security_tests()
        assert results["tests_run"] == 5
        # Tidak boleh ada error di detail
        error_details = [d for d in results["details"] if "error" in d.get("reason", "").lower()]
        assert error_details == [], f"Penetration tests raised errors: {error_details}"

    @pytest.mark.asyncio
    async def test_api_key_leak_safe_without_keys(self):
        """Tanpa API key, test leak harus pass (tidak crash)"""
        tester = PenetrationTester()
        result = await tester._test_api_key_leak()
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_sql_injection_test_passes(self):
        tester = PenetrationTester()
        result = await tester._test_sql_injection_resistance()
        assert result["passed"] is True


class TestDependencyAuditor:
    """Test dependency auditing"""

    def test_default_requirements_path_is_relative(self):
        """Bug lama: path hard-coded /app/requirements.txt"""
        auditor = DependencyAuditor()
        assert auditor.requirements_path.exists(), (
            f"requirements.txt tidak ditemukan di {auditor.requirements_path}"
        )
        assert "/app/" not in str(auditor.requirements_path) or str(auditor.requirements_path).startswith("/app") is False

    @pytest.mark.asyncio
    async def test_scan_dependencies(self):
        """Scan requirements.txt nyata -> terisi jumlah package (OSV di-mock agar deterministik)"""
        auditor = DependencyAuditor()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"vulns": []}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.security.hardening.httpx.AsyncClient", return_value=mock_client):
            results = await auditor.scan_dependencies()

        assert "error" not in results
        assert results["scanned"] > 0
        assert mock_client.post.await_count == results["scanned"]

    @pytest.mark.asyncio
    async def test_scan_detects_vulnerability(self):
        """Package dengan vuln dari OSV masuk ke laporan"""
        auditor = DependencyAuditor()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "vulns": [{"id": "GHSA-TEST", "summary": "Test vuln", "severity": "HIGH"}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.security.hardening.httpx.AsyncClient", return_value=mock_client):
            results = await auditor.scan_dependencies()

        assert results["vulnerable"] >= 1
        assert results["vulnerabilities"][0]["id"] == "GHSA-TEST"

    @pytest.mark.asyncio
    async def test_scan_missing_file(self, tmp_path):
        """File requirements tidak ada -> error terstruktur, bukan crash"""
        auditor = DependencyAuditor(requirements_path=tmp_path / "tidak_ada.txt")
        results = await auditor.scan_dependencies()
        assert "error" in results

    def test_generate_audit_report(self):
        auditor = DependencyAuditor()
        report = auditor.generate_audit_report({
            "scanned": 10,
            "vulnerable": 1,
            "vulnerabilities": [{
                "package": "requests",
                "version": "2.31.0",
                "id": "GHSA-1234",
                "severity": "HIGH",
                "summary": "Test vulnerability",
            }],
        })
        assert "# Security Audit Report" in report
        assert "requests" in report
        assert "GHSA-1234" in report

    def test_generate_audit_report_clean(self):
        auditor = DependencyAuditor()
        report = auditor.generate_audit_report({"scanned": 10, "vulnerable": 0, "vulnerabilities": []})
        assert "No known vulnerabilities" in report
