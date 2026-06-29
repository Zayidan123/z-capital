"""
Tests for the FastAPI health endpoint
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_check(self):
        """Test /health endpoint returns running status"""
        client = TestClient(app)
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
    
    def test_health_response_format(self):
        """Test health endpoint response format"""
        client = TestClient(app)
        response = client.get("/health")
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data or "version" in data
