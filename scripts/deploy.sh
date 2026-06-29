#!/bin/bash
# Script untuk rebuild dan restart Crypto Oracle AI dengan fitur keamanan baru

set -e

echo "🔐 Crypto Oracle AI - Security Hardening Deployment"
echo "======================================================"

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker-compose down

# Rebuild with no cache to ensure latest security patches
echo "🔨 Rebuilding Docker image with security hardening..."
docker-compose build --no-cache

# Start services
echo "🚀 Starting services..."
docker-compose up -d

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check container status
echo "📊 Container Status:"
docker-compose ps

# Show logs
echo ""
echo "📝 Recent logs (last 20 lines):"
docker-compose logs --tail=20

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🌐 Dashboard URL: http://localhost:8080/dashboard"
echo "🏥 Health Check: http://localhost:8080/health"
echo "📚 API Docs: http://localhost:8080/docs"
echo ""
echo "🔒 Security Features Enabled:"
echo "   - Non-root user in container"
echo "   - Multi-layer signal validation"
echo "   - Dependency vulnerability scanning"
echo "   - Penetration testing module"
echo "   - Secrets manager integration"
echo ""
echo "To view real-time logs: docker-compose logs -f"
echo "To stop services: docker-compose down"
