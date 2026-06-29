# 🚀 Crypto Oracle AI - Enterprise Edition

## Sistem Deteksi Dini Pump/Dump Terdesentralisasi dengan Fitur AI Lengkap

Sistem monitoring crypto 24/7 yang memantau CEX (Binance), DEX, On-Chain (Etherscan), dan Berita (CryptoPanic) dengan fitur enterprise lengkap.

---

## 📋 Daftar Fitur Lengkap

### ✅ Modul Inti (Original)
1. **Real-Time Streamer** - WebSocket Binance untuk semua pair USDT
2. **Deep Dive Analyzer** - Analisis Etherscan + CryptoPanic
3. **Telegram Notifier** - Notifikasi sinyal trading
4. **Database PostgreSQL** - Penyimpanan data async
5. **Health Check API** - Endpoint untuk cloud deployment

### 🆕 Modul Keamanan (Security)
6. **Honeypot Detector** - Deteksi token berbahaya
   - Analisis buy/sell tax
   - Pemeriksaan liquidity lock
   - Verifikasi kontrak
   - Distribusi holder
   - Trading restrictions

7. **Liquidity Lock Checker** - Status lock likuiditas multi-platform
8. **Holder Distribution Analyzer** - Analisis konsentrasi whale dengan Gini coefficient

### 🤖 Modul AI & Machine Learning
9. **Pattern Recognizer** - Pengenalan pola pump/dump
   - Classic pump pattern
   - Slow accumulation
   - Whale manipulation
   - Coordinated pump

10. **Sentiment Analyzer** - NLP sentiment analysis
    - Keyword-based scoring dengan bobot
    - Multi-source analysis
    - Social volume tracking

11. **Whale Tracker** - Pelacakan transaksi besar
    - Large transaction monitoring
    - Net whale flow analysis
    - Known whale wallet tracking

### 💼 Modul Trading & Eksekusi
12. **Risk Manager** - Manajemen risiko otomatis
    - Dynamic stop-loss (ATR-based)
    - Multiple take-profit levels
    - Position sizing optimal

13. **Auto Sniper** - Eksekusi otomatis pada sinyal confirmed
14. **Portfolio Tracker** - Tracking performa trading dengan metrics lengkap

### 🔗 Modul Multi-Chain
15. **Multi-Chain Monitor** - Support 5 chains
    - Ethereum, BSC, Polygon, Arbitrum, Optimism
    - Cross-chain price monitoring
    - Arbitrage opportunity detection

16. **Arbitrage Scanner** - CEX-DEX arbitrage
    - Price difference scanning
    - Fee-adjusted profit calculation
    - Multi-exchange support

### 📊 Modul Dashboard & Observabilitas
17. **Real-Time Dashboard** - Metrics live system
18. **Alert System** - Advanced alerting dengan rate limiting
19. **Backtest Engine** - Backtesting strategi dengan Sharpe ratio

### ⚙️ Modul Infrastruktur
20. **Redis Cache** - Caching layer untuk performance
21. **Rate Limiter** - Distributed rate limiting
22. **Horizontal Scaler** - Multi-instance coordination
23. **Message Queue** - Inter-service communication

---

## 🏗️ Arsitektur Proyek

```
/workspace/
├── app/
│   ├── config/           # Configuration loader
│   ├── security/         # Honeypot detector, liquidity checker
│   ├── ai/               # Pattern recognition, sentiment analysis
│   ├── trading/          # Risk management, auto-snipe
│   ├── multichain/       # Multi-chain support, arbitrage
│   ├── dashboard/        # Real-time dashboard, alerts, backtest
│   ├── infrastructure/   # Redis, rate limiting, scaling
│   ├── database.py       # Async PostgreSQL
│   ├── streamer.py       # Binance WebSocket
│   ├── analyzer.py       # Deep dive analysis
│   ├── notifier.py       # Telegram bot
│   └── main.py           # Orchestrator + FastAPI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
cd /workspace
cp .env.example .env
# Edit .env dengan API keys Anda
```

### 2. Konfigurasi Environment Variables

Edit file `.env`:

```env
# Database
DATABASE_URL=postgresql://crypto_user:crypto_password@postgres:5432/crypto_oracle

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Etherscan (untuk analisis on-chain)
ETHERSCAN_API_KEY=your_etherscan_key

# CryptoPanic (untuk news sentiment)
CRYPTOPANIC_API_KEY=your_cryptopanic_key

# Redis (optional - untuk caching & scaling)
REDIS_URL=redis://redis:6379

# Application Settings
VOLUME_SPIKE_THRESHOLD=300
VOLUME_WINDOW_MINUTES=5
LOG_LEVEL=INFO
```

### 3. Deploy dengan Docker Compose

```bash
# Build dan jalankan semua services
docker-compose up --build

# Atau jalankan dengan Redis (untuk fitur scaling)
docker-compose --profile with-redis up --build
```

### 4. Verifikasi Deployment

```bash
# Check health endpoint
curl http://localhost:8080/health

# View logs
docker-compose logs -f app
```

---

## ☁️ Deployment ke Cloud

### Railway.app

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login dan init project
railway login
railway init

# Add PostgreSQL
railway add postgresql

# Set environment variables
railway variables set TELEGRAM_BOT_TOKEN=xxx
railway variables set TELEGRAM_CHAT_ID=xxx
railway variables set ETHERSCAN_API_KEY=xxx
railway variables set CRYPTOPANIC_API_KEY=xxx

# Deploy
railway up
```

### Render.com

1. Push code ke GitHub
2. Buat Web Service baru di Render
3. Connect repository GitHub
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python -m app.main`
6. Add PostgreSQL dari Render dashboard
7. Set environment variables
8. Deploy!

### VPS dengan Docker

```bash
# SSH ke VPS
ssh user@your-vps-ip

# Clone repository
git clone <your-repo>
cd crypto-oracle-ai

# Copy .env file
scp .env user@your-vps-ip:~/crypto-oracle-ai/

# Run with Docker Compose
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

---

## 📡 API Endpoints

| Endpoint | Method | Deskripsi |
|----------|--------|-----------|
| `/health` | GET | Health check untuk cloud monitoring |
| `/` | GET | API information |
| `/docs` | GET | Swagger UI documentation |

---

## 📊 Database Schema

### Tables:
- `anomali_logs` - Log volume anomalies
- `smart_wallets` - Database wallet pintar
- `signals_sent` - History sinyal Telegram

---

## 🔧 Fitur Advanced Usage

### Enable Auto-Sniping (Experimental)

```python
# Di main.py atau module terpisah
from app.trading import AutoSniper, RiskManager

auto_sniper = AutoSniper(db, risk_manager)
auto_sniper.enable()  # ⚠️ Gunakan dengan risiko sendiri!
```

### Run Backtest

```python
from app.dashboard import BacktestEngine

backtest = BacktestEngine(db)
result = await backtest.run_backtest(
    symbol="BTCUSDT",
    days=7,
    volume_threshold=300.0
)
print(result['performance'])
```

### Check Token Safety

```python
from app.security import HoneypotDetector

detector = HoneypotDetector(db)
await detector.start()

safety_result = await detector.check_token_safety(
    token_address="0x...",
    symbol="NEWCOIN"
)
print(f"Risk Score: {safety_result['risk_score']}")
print(f"Recommendation: {safety_result['recommendation']}")
```

---

## ⚠️ Disclaimer Penting

> **PERINGATAN**: Software ini disediakan "AS IS" untuk tujuan edukasi dan riset. 
> 
> - ⛔ Bukan financial advice
> - ⛔ Tidak menjamin profit
> - ⛔ Gunakan risiko sendiri (DYOR)
> - ⛔ Test dulu di testnet/paper trading
> - ⛔ Jangan invest lebih dari yang sanggup hilang

---

## 📈 Roadmap Fitur Future

- [ ] Integration dengan DEX aggregators (1inch, Paraswap)
- [ ] Machine Learning model training pipeline
- [ ] Telegram bot commands untuk control
- [ ] Web dashboard dengan React/Vue
- [ ] Support lebih banyak chains (Solana, Avalanche, etc.)
- [ ] Smart contract integration untuk auto-trading

---

## 🤝 Contributing

Pull requests welcome! Untuk major changes, please open issue terlebih dahulu.

---

## 📄 License

MIT License - See LICENSE file for details.

---

## 📞 Support

Untuk pertanyaan dan dukungan:
- GitHub Issues: [Link]
- Telegram Group: [Link]
- Documentation: [Link]

---

**Dibangun dengan ❤️ oleh Senior Cloud Architect & Full-Stack Quant Developer**

*Happy Trading & Stay Safe! 🚀*