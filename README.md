# 🚀 Crypto Oracle AI - Enterprise Edition v2.0

## Sistem Deteksi Dini Pump/Dump Terdesentralisasi dengan Fitur AI Lengkap

Sistem monitoring crypto 24/7 yang memantau CEX (Binance), DEX, On-Chain (Etherscan), dan Berita (CryptoPanic) dengan fitur enterprise lengkap.

![Status](https://img.shields.io/badge/status-production%20ready-brightgreen) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Tests](https://img.shields.io/badge/tests-68%20passed-success) ![License](https://img.shields.io/badge/license-MIT-green)

---

## 📋 Daftar Fitur Lengkap

### ✅ Modul Inti (Core)
1. **Real-Time Streamer** - WebSocket Binance untuk semua pair USDT dengan deteksi volume spike berbasis *delta interval* (akurat, bukan snapshot kumulatif)
2. **Deep Dive Analyzer** - Analisis Etherscan (smart money) + CryptoPanic (news sentiment) secara paralel
3. **Telegram Notifier** - Notifikasi sinyal trading dengan level urgensi (LOW/MEDIUM/HIGH) dan saran manajemen risiko
4. **Database PostgreSQL** - Penyimpanan data async (asyncpg connection pool) dengan indeks optimasi
5. **Health Check API** - Endpoint untuk cloud deployment & monitoring

### 🛡️ Modul Keamanan (Security)
6. **Honeypot Detector** - Deteksi token berbahaya via GoPlus Security API
   - Analisis buy/sell tax, liquidity lock, verifikasi kontrak, distribusi holder, trading restrictions
   - Risk score 0-100 dengan rekomendasi SAFE/LOW_RISK/MEDIUM_RISK/HIGH_RISK
7. **Liquidity Lock Checker** - Status lock likuiditas multi-platform
8. **Holder Distribution Analyzer** - Analisis konsentrasi whale dengan Gini coefficient
9. **Multi-layer Signal Validator** - 6 lapis validasi (volume, price, smart money, sentiment, liquidity, honeypot) untuk mencegah false positive
10. **Penetration Test Simulation** - Audit keamanan mandiri (env exposure, API key leak, SQL injection, rate limiting, container isolation)
11. **Dependency Auditor** - Scan kerentanan dependensi via OSV.dev API

### 🤖 Modul AI & Machine Learning
12. **Pattern Recognizer** - Pengenalan pola pump/dump (classic pump, slow accumulation, whale manipulation, coordinated pump) dengan RSI & moving average
13. **Sentiment Analyzer** - NLP berbasis lexicon berbobot dengan multi-source analysis
14. **Whale Tracker** - Pelacakan transaksi besar (> $100k) dan net whale flow

### 💼 Modul Trading & Eksekusi
15. **Risk Manager** - Dynamic stop-loss berbasis volatilitas (ATR), multiple take-profit levels (20/40/60%), position sizing optimal (2% risk per trade)
16. **Auto Sniper** - Eksekusi otomatis pada sinyal confirmed dengan confidence scaling (⚠️ experimental)
17. **Portfolio Tracker** - Tracking performa trading dengan win rate, PnL, dan ROI

### 🔗 Modul Multi-Chain
18. **Multi-Chain Monitor** - Support 5 chains: Ethereum, BSC, Polygon, Arbitrum, Optimism
19. **Arbitrage Scanner** - CEX-DEX arbitrage dengan kalkulasi profit setelah biaya gas

### 📊 Modul Dashboard & Observabilitas
20. **Real-Time Dashboard** - Monitoring live via WebSocket (anomaly feed, signal confirmation, stats auto-refresh 30s)
21. **Alert System** - Alerting dengan rate limiting per rule per symbol
22. **Backtest Engine** - Backtesting strategi dengan win rate, Sharpe ratio, dan max drawdown

### ⚙️ Modul Infrastruktur
23. **Redis Cache** - Caching layer dengan get-or-set pattern dan pub/sub
24. **Rate Limiter** - Distributed rate limiting (Redis sliding window + fallback in-memory)
25. **Horizontal Scaler** - Koordinasi multi-instance dengan heartbeat
26. **Message Queue** - Antrean pesan Redis untuk komunikasi antar service

---

## 🏗️ Arsitektur Proyek

```
z-capital/
├── app/
│   ├── config/           # Configuration loader (pydantic-settings v2)
│   ├── security/         # Honeypot detector, signal validator, pentest, dependency audit
│   ├── ai/               # Pattern recognition, sentiment analysis, whale tracker
│   ├── trading/          # Risk management, auto-snipe, portfolio tracking
│   ├── multichain/       # Multi-chain support, arbitrage scanner
│   ├── dashboard/        # Metrics, alert system, backtest engine
│   ├── infrastructure/   # Redis cache, rate limiting, horizontal scaling
│   ├── ui/               # Dashboard routes (FastAPI + WebSocket + Jinja2)
│   ├── database.py       # Async PostgreSQL (asyncpg pool)
│   ├── streamer.py       # Binance WebSocket + volume spike detection
│   ├── analyzer.py       # Deep dive analysis (Etherscan + CryptoPanic)
│   ├── notifier.py       # Telegram bot notifications
│   ├── logging_config.py # Structured logging (JSON + console)
│   └── main.py           # Orchestrator + FastAPI app
├── tests/                # Test suite lengkap (68 tests, semua mock - tanpa DB/network)
├── scripts/deploy.sh     # Deployment helper
├── Dockerfile            # Multi-stage build, non-root user, healthcheck
├── docker-compose.yml    # PostgreSQL + Redis (optional) + App
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
git clone https://github.com/Zayidan123/z-capital.git
cd z-capital
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env dengan API keys Anda
```

### 2. Konfigurasi Environment Variables

Edit file `.env` (lihat `.env.example` untuk daftar lengkap):

```env
# Database
DATABASE_URL=postgresql://crypto_user:crypto_password@localhost:5432/crypto_oracle

# Telegram (untuk notifikasi sinyal)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Etherscan (analisis on-chain smart money)
ETHERSCAN_API_KEY=your_etherscan_key

# CryptoPanic (news sentiment)
CRYPTOPANIC_API_KEY=your_cryptopanic_key

# Redis (optional - caching & scaling)
REDIS_HOST=localhost
REDIS_PORT=6379
# atau langsung URL:
# REDIS_URL=redis://localhost:6379

# Application Settings
VOLUME_SPIKE_THRESHOLD=300
VOLUME_WINDOW_MINUTES=5
HEALTH_CHECK_PORT=8080
LOG_LEVEL=INFO
```

### 3. Jalankan Langsung (tanpa Docker)

```bash
python -m app.main
# Server berjalan di http://localhost:8080
```

### 4. Deploy dengan Docker Compose (disarankan)

```bash
# Build dan jalankan semua services
docker compose up --build

# Atau dengan Redis (untuk fitur caching & scaling)
docker compose --profile with-redis up --build
```

### 5. Verifikasi Deployment

```bash
# Health check
curl http://localhost:8080/health

# Buka dashboard
open http://localhost:8080/dashboard/

# Lihat logs
docker compose logs -f app
```

---

## 📡 API Endpoints

| Endpoint | Method | Deskripsi |
|----------|--------|-----------|
| `/` | GET | Informasi API |
| `/health` | GET | Health check untuk cloud monitoring |
| `/docs` | GET | Swagger UI documentation |
| `/dashboard/` | GET | Dashboard real-time monitoring |
| `/dashboard/api/stats` | GET | Statistik sistem & sinyal terbaru |
| `/dashboard/api/anomalies` | GET | Daftar anomali volume terbaru (support `?limit=` & `?symbol=`) |
| `/dashboard/api/export/signals.csv` | GET | Export sinyal ke file CSV (support `?limit=`) |
| `/dashboard/api/security/audit` | GET | Jalankan audit keamanan (dependency scan + pentest) |
| `/dashboard/api/signals/validate/{symbol}` | GET | Validasi sinyal multi-layer untuk symbol |
| `/dashboard/ws/updates` | WebSocket | Update real-time (anomaly, signal, stats auto-push tiap 30s) |

---

## 📊 Database Schema

| Tabel | Fungsi |
|-------|--------|
| `anomali_logs` | Log volume anomaly (symbol, price, spike %, volume) |
| `smart_wallets` | Database wallet pintar (address, chain, win rate) |
| `signals_sent` | Riwayat sinyal Telegram (status sent/failed) |

---

## 🧪 Testing

Test suite menggunakan pytest dengan mock penuh (tidak butuh PostgreSQL/network):

```bash
# Jalankan semua test
pytest tests/ -v

# Dengan coverage
pytest tests/ --cov=app --cov-report=term-missing

# Test tertentu saja
pytest tests/test_streamer_volume.py -v
```

**Status saat ini: 87 tests passing** ✅ (mencakup config, database, streamer volume tracker, analyzer, notifier, AI module, security hardening, dan seluruh endpoint FastAPI termasuk anomalies & CSV export).

---

## 🔧 Fitur Advanced Usage

### Enable Auto-Sniping (Experimental)

```python
from app.trading import AutoSniper, RiskManager

risk_manager = RiskManager(db)
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
    volume_threshold=300.0,
)
print(result['performance'])  # win_rate, sharpe_ratio, max_drawdown
```

### Check Token Safety

```python
from app.security import HoneypotDetector

detector = HoneypotDetector(db)
await detector.start()

safety = await detector.check_token_safety(
    token_address="0x...",
    symbol="NEWCOIN",
)
print(f"Risk Score: {safety['risk_score']}")       # 0-100
print(f"Recommendation: {safety['recommendation']}")  # SAFE/HIGH_RISK/...
```

---

## 🛠️ Perbaikan & Optimasi (Changelog v2.0.1)

Repositori ini telah melalui audit menyeluruh. Berikut ringkasan perbaikan:

### 🐛 Bug Kritis yang Diperbaiki
| # | Bug | Lokasi | Dampak |
|---|-----|--------|--------|
| 1 | Dashboard mem-fetch `/api/stats`, `/api/security/audit`, dan WebSocket `/ws/updates` tanpa prefix `/dashboard` → **semua 404**, dashboard kosong | `app/ui/templates/dashboard.html` | Dashboard tidak berfungsi sama sekali |
| 2 | `AttributeError: Settings has no attribute TELEGRAM_BOT_TOKEN / REDIS_HOST` (field didefinisikan lowercase) | `app/security/hardening.py` | Endpoint audit keamanan crash 100% |
| 3 | Perbandingan datetime timezone-aware (asyncpg TIMESTAMPTZ) vs naive `datetime.utcnow()` → **TypeError** | `app/dashboard/__init__.py` (BacktestEngine) | Backtest crash pada data riil |
| 4 | Logika deteksi volume spike membandingkan kumulatif 24h vs rata-rata snapshot kumulatif → spike 300% **tidak pernah terdeteksi** | `app/streamer.py` | Fitur inti tidak berfungsi |
| 5 | Counter `sources_analyzed` di sentiment analyzer selalu bernilai 1 + `UnboundLocalError` saat semua input kosong | `app/ai/__init__.py` | Confidence score salah |
| 6 | Seluruh test suite meng-import class/method yang tidak ada (`Analyzer`, `Notifier`, `get_db`, ...) → **collection error** | `tests/` | CI merah, tidak ada regresi terdeteksi |
| 7 | Path template `/app/ui/templates` dan `/app/requirements.txt` hard-coded → crash saat dijalankan di luar Docker | `app/ui/routes.py`, `app/security/hardening.py` | App tidak bisa dijalankan lokal |
| 8 | `bot.session.close()` tidak ada di python-telegram-bot v20+ | `app/notifier.py` | Shutdown error |
| 9 | Heartbeat `HorizontalScaler` tidak pernah di-cancel + referensi task asyncio tidak disimpan (risiko GC) | `app/infrastructure/__init__.py`, `app/streamer.py`, `app/main.py` | Memory leak / task hilang diam-diam |
| 10 | Penetration test `API Key Leakage` crash saat API key `None` (`None in str`) | `app/security/hardening.py` | Audit gagal |
| 11 | `.gitignore` berisi kalimat teks biasa (bukan pattern) → `__pycache__/`, `.coverage`, `.env` ter-commit | `.gitignore` | Kebocoran artifact & risiko keamanan |
| 12 | Regex parser versi requirements di-anchored `^` → 0 package ter-scan | `app/security/hardening.py` | Dependency audit tidak berfungsi |

### ⚡ Optimasi
- **Volume tracker** menggunakan `deque` (O(1) popleft) untuk windowing, menggantikan list-comprehension O(n) per tick per symbol
- **Referensi asyncio task** disimpan dengan done-callback (`_background_tasks`) sesuai rekomendasi dokumentasi Python — mencegah task di-garbage-collect selesai lebih awal
- **Graceful shutdown** semua komponen dibungkus try/except; `BinanceStreamer.stop()` membatalkan cooldown tasks; websocket close aman
- **WebSocket broadcast** dengan pembersihan koneksi mati yang aman (mencegah `ValueError: list.remove`)
- **Uptime dashboard** dihitung riil (bukan selalu 0) dan live feed anomaly/signal dikirim ke dashboard via WebSocket
- **Ukuran dependency** diperkecil: `scikit-learn` & `pytz` dihapus (tidak dipakai, `pytz` diganti stdlib `zoneinfo`)
- **Pydantic v2** migration: `class Config` → `model_config = SettingsConfigDict(...)` (menghilangkan deprecation warning)
- **`datetime.utcnow()`** (deprecated di Python 3.12) diganti `datetime.now(timezone.utc)` di seluruh codebase
- **XSS protection** di dashboard (escapeHtml untuk semua data dinamis) + exponential backoff untuk reconnect WebSocket
- **Validasi settings** dengan `Field(ge=..., gt=...)` untuk port/threshold

### 🧪 Test Suite Baru
- 87 test dengan mocking penuh (Postgres, HTTP, Telegram di-mock) — berjalan cepat & deterministik di CI
- Mencakup: config validation, database CRUD (mock pool), volume tracker delta logic, pattern recognizer, sentiment analyzer, whale tracker, signal validator, penetration tester, dependency auditor, dan semua endpoint dashboard

### ✨ v2.1 — Dashboard Overhaul & Fitur Baru
- **Tabel Recent Volume Anomalies** — monitor anomali langsung dari dashboard (endpoint `/api/anomalies` baru)
- **Export CSV** — unduh riwayat sinyal via `/api/export/signals.csv`
- **Sortable tables** — klik header kolom untuk sorting (symbol, price, spike, time)
- **Auto-refresh toggle + tombol refresh manual**
- **Stats auto-push via WebSocket** tiap 30 detik dari server (semua client sinkron tanpa polling)
- **Styling overhaul**: connection badge dinamis (LIVE/RECONNECTING/OFFLINE), jam live WIB di header, skeleton loading shimmer, card accent per-metrik, scrollbar custom, favicon, mobile responsive penuh, dukungan `prefers-reduced-motion`

---

## ☁️ Deployment ke Cloud

### Railway.app

```bash
npm install -g @railway/cli
railway login
railway init
railway add postgresql
railway variables set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx ETHERSCAN_API_KEY=xxx CRYPTOPANIC_API_KEY=xxx
railway up
```

### Render.com

1. Push code ke GitHub → buat Web Service baru
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `python -m app.main`
4. Add PostgreSQL dari Render dashboard
5. Set environment variables → Deploy

### VPS dengan Docker

```bash
git clone https://github.com/Zayidan123/z-capital.git
cd z-capital
cp .env.example .env  # isi API keys
docker compose up -d
docker compose logs -f
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

## 📈 Roadmap

- [ ] Integration dengan DEX aggregators (1inch, Paraswap)
- [ ] Machine Learning model training pipeline
- [ ] Telegram bot commands untuk control
- [ ] Support lebih banyak chains (Solana, Avalanche, dll)
- [ ] Smart contract integration untuk auto-trading

---

## 🤝 Contributing

Pull requests welcome! Untuk major changes, silakan buka issue terlebih dahulu. Jalankan `pytest` dan pastikan semua test hijau sebelum submit PR.

---

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

---

**Dibangun dengan ❤️ oleh Senior Cloud Architect & Full-Stack Quant Developer**

*Happy Trading & Stay Safe! 🚀*
