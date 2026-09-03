# 🚀 Crypto Oracle AI - Enterprise Edition v2.10

## Sistem Deteksi Dini Pump/Dump Terdesentralisasi dengan Fitur AI Lengkap

Sistem monitoring crypto 24/7 yang memantau CEX (Binance), DEX, On-Chain (Etherscan), dan Berita (CryptoPanic) dengan fitur enterprise lengkap.

![Status](https://img.shields.io/badge/status-production%20ready-brightgreen) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Tests](https://img.shields.io/badge/tests-389%20passed-success) ![License](https://img.shields.io/badge/license-MIT-green)

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
├── tests/                # Test suite lengkap (389 tests, semua mock - tanpa DB/network)
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

# Dashboard API (optional)
# DASHBOARD_API_KEY=your_secret_key
DASHBOARD_RATE_LIMIT=120
DASHBOARD_RATE_LIMIT_WINDOW=60

# Alert history retention (v2.5) - dapat dioverride runtime dari dashboard (v2.6)
ALERT_HISTORY_RETENTION_DAYS=7
ALERT_RETENTION_INTERVAL_MINUTES=60

# Salt enkripsi secret runtime settings (v2.6, optional - fallback ke DATABASE_URL)
# DASHBOARD_SECRET_SALT=change_me_random_string
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
| `/dashboard/api/symbols` | GET | Ringkasan per-symbol (jumlah anomali, harga terakhir, rata-rata spike) |
| `/dashboard/api/sparkline/{symbol}` | GET | Riwayat harga kronologis untuk grafik sparkline (`?points=10..200`) |
| `/dashboard/api/symbol/{symbol}` | GET | Detail lengkap satu symbol: agregat + riwayat harga + anomali (`?history_points=10..500`) |
| `/dashboard/api/alerts/rules` | GET | Daftar alert rules (metadata + threshold, otomatis menerapkan threshold tersimpan DB) |
| `/dashboard/api/alerts/rules/{name}` | PUT | Ubah threshold rule editable + persist ke DB (body `{"threshold": number}`, response flag `persisted`) |
| `/dashboard/api/alerts/rule-stats` | GET | **v2.7** Agregasi alert per-rule untuk audit sparkline — **v2.10 `?bucket=day`** untuk audit 7-hari (slot hari kosong diisi 0, clamp 1..30 hari; bucket=hour tetap 1..168 jam; `total` + `last_fired` per rule) |
| `/dashboard/api/alerts/rules/export` | GET | **v2.7** Export semua alert rules sebagai file JSON attachment (backup/migrasi antar instans) |
| `/dashboard/api/alerts/rules/import` | POST | **v2.7** Bulk import threshold rules dari JSON export (status per-item: `updated`/`unknown`/`not_editable`/`invalid_threshold` — satu item jelek tidak menggagalkan batch) |
| `/dashboard/api/alerts/rules/bulk` | POST | **v2.8** Terapkan SATU threshold ke banyak rule sekaligus (body `{"names": [1..50 nama], "threshold": >= 0}`; status per-item konsisten dgn import; NaN/Infinity/negatif ditolak 400) |
| `/dashboard/api/webhook/status` | GET | **v2.8** Status channel webhook (flag configured, host tersamarkan `scheme://host` - path/query TIDAK pernah bocor, hasil delivery terakhir) |
| `/dashboard/api/webhook/test` | POST | **v2.8** Kirim payload test JSON ke webhook terkonfigurasi (gagal delivery = hasil `sent:false` + reason, bukan error endpoint; **v2.9** hasil dicatat ke delivery log + field `attempts`) |
| `/dashboard/api/webhook/deliveries` | GET | **v2.9** Log delivery webhook terbaru dari DB (event/ok/status_code/reason/attempts/duration_ms/rule/symbol, `?limit=1..200`; fallback in-memory saat DB down) |
| `/dashboard/api/webhook/health` | GET | **v2.10** Ringkasan kesehatan delivery 24 jam: total/ok/fail, success rate, rata-rata durasi & attempts, alasan gagal terakhir, jumlah outbox pending (`?hours=1..720`; fallback in-memory saat DB down) |
| `/dashboard/api/webhook/outbox` | GET | **v2.10** Antrean alert yang gagal terkirim dan menunggu replay (metadata rule/symbol/attempts/reason/waktu terurut terlama dulu — payload alert TIDAK disertakan, `?limit=1..200`) |
| `/dashboard/api/webhook/outbox/replay` | POST | **v2.10** Kirim ulang antrean outbox (maks 50 per panggilan): sukses dihapus + dicatat ke delivery log sebagai event `replay`, gagal tetap antre dengan attempts naik; `not_configured` bila URL belum dipasang |
| `/dashboard/api/alerts/history` | GET | Riwayat alert ter-trigger dari DB (persisten; fallback in-memory, flag `source`; **v2.6 filter `?symbol=` & `?hours=`**, **v2.9 `?priority=`** high/medium/low — cocok untuk data `HIGH` maupun `high` via LOWER, `?limit=1..200`) |
| `/dashboard/api/alerts/heatmap` | GET | Agregasi alert per-symbol per-jam untuk heat map (`?hours=6..168`) |
| `/dashboard/api/alerts/heatmap.csv` | GET | **v2.6** Export agregasi heat map sebagai CSV (`?hours=6..168`; kolom symbol/hour/alert_count/severity) |
| `/dashboard/api/settings` | GET | **v2.6** Runtime settings: nilai efektif, default, batasan, flag override/persisted — secret tidak pernah dikembalikan |
| `/dashboard/api/alerts/retention` | GET | Info retensi alert_history: konfigurasi, hasil prune terakhir, statistik tabel |
| `/dashboard/api/alerts/prune` | POST | Prune manual alert_history (body opsional `{"days": 1..365}`; default pengaturan retensi) |
| `/dashboard/api/telegram/status` | GET | Status notifikasi Telegram (flag configured, username bot, chat id tersamarkan — **tanpa token**) |
| `/dashboard/api/telegram/test` | POST | Kirim pesan test ke Telegram (response `sent` + `reason`, gagal kirim = hasil bukan error) |
| `/dashboard/api/settings` | PUT | **v2.6** Terapkan + persist runtime settings (int di-clamp dengan warning; token Telegram diverifikasi ke API lalu disimpan terenkripsi Fernet) |
| `/dashboard/api/settings/export` | GET | **v2.9** Export SEMUA runtime settings sebagai JSON attachment — secret hanya diekspor sebagai blob terenkripsi `enc:v1` (plaintext TIDAK pernah keluar), int bernilai efektif |
| `/dashboard/api/settings/import` | POST | **v2.9** Restore settings dari file export (status per-item: `applied`/`secret_applied`/`rejected`/`undecryptable`/`invalid_value`/`unknown_key`; **secret plaintext ditolak**, blob kunci instance lain ditolak; webhook_url langsung dipasang ke dispatcher) |
| `/dashboard/manifest.webmanifest` | GET | **v2.6** PWA manifest (install dashboard ke homescreen; ikon 192/512) |
| `/dashboard/api/backtest/{symbol}` | POST | Backtest strategi volume-spike (body `{"days": 1..90, "volume_threshold": 10..10000}`) |
| `/dashboard/api/export/signals.csv` | GET | Export sinyal ke file CSV (support `?limit=`) |
| `/dashboard/api/security/audit` | GET | Jalankan audit keamanan (dependency scan + pentest) |
| `/dashboard/api/signals/validate/{symbol}` | GET | Validasi sinyal multi-layer untuk symbol |
| `/dashboard/ws/updates` | WebSocket | Update real-time (anomaly, signal, **alert_triggered**, stats auto-push tiap 30s) |

> 🔐 **Opsi autentikasi API**: set environment variable `DASHBOARD_API_KEY` untuk mewajibkan header `X-API-Key` pada semua endpoint `/dashboard/api/*` (cocok saat dashboard diekspos ke publik). Jika tidak di-set, semua endpoint terbuka (mode lokal). Halaman HTML & WebSocket tidak terpengaruh.
>
> 🚦 **Rate limiting**: semua endpoint `/dashboard/api/*` dibatasi **120 request/menit per IP** (sliding window in-memory, per-endpoint). Melebihi kuota → HTTP 429 + header `Retry-After`. Atur via `DASHBOARD_RATE_LIMIT` (0 = nonaktif) dan `DASHBOARD_RATE_LIMIT_WINDOW` (detik).
>
> 🧹 **Retensi alert_history (v2.5)**: baris lebih tua dari `ALERT_HISTORY_RETENTION_DAYS` (default 7, 0 = off) dihapus otomatis oleh loop background tiap `ALERT_RETENTION_INTERVAL_MINUTES` (default 60). **v2.6**: nilai env dapat dioverride dari dashboard (System Settings) dan loop membaca override tiap siklus. Prune manual tersedia via tombol **Prune Now** di dashboard atau `POST /dashboard/api/alerts/prune`.
>
> ⚙️ **Runtime settings (v2.6)**: ubah konfigurasi tanpa restart via panel **System Settings** (tersimpan di tabel `app_settings`, bertahan restart). Key yang tersedia: `alert_history_retention_days` (0–365), `dashboard_refresh_seconds` (10–600), `anomaly_feed_limit` (10–200), plus konfigurasi Telegram runtime (`telegram_bot_token` dienkripsi Fernet dengan kunci derivasi dari `DASHBOARD_SECRET_SALT`/DATABASE_URL — write-only, tidak pernah dikirim balik ke browser; `telegram_chat_id`). Nilai selain default ditandai badge **override**. **v2.9**: seluruh settings bisa di-backup/restore via tombol **Export/Import** (JSON; secret tetap terenkripsi dalam file — file export hanya bisa dibuka instance dengan kunci yang sama).

---

## 📊 Database Schema

| Tabel | Fungsi |
|-------|--------|
| `anomali_logs` | Log volume anomaly (symbol, price, spike %, volume) |
| `smart_wallets` | Database wallet pintar (address, chain, win rate) |
| `signals_sent` | Riwayat sinyal Telegram (status sent/failed) |
| `alert_rules` | Threshold alert rules yang diubah via dashboard (**survive restart**, v2.4) |
| `alert_history` | Riwayat alert ter-trigger (rule, priority, symbol, data JSONB — persisten v2.4; auto-prune via retensi v2.5) |
| `app_settings` | Runtime settings key-value (v2.6): retensi, refresh interval, feed limit, konfigurasi Telegram (secret terenkripsi) — survive restart |
| `webhook_deliveries` | Log hasil pengiriman webhook (v2.9): event test/alert, ok, status code, reason, jumlah attempts (retry), durasi, rule/symbol — audit tahan restart, di-prune bersama retensi alert_history |
| `webhook_outbox` | Antrean delivery gagal total (v2.10): payload alert JSONB + rule/symbol + attempts + last_reason + waktu antre — di-replay otomatis oleh loop background tiap 5 menit atau manual via tombol **Replay** di dashboard, dihapus saat sukses, di-prune bersama retensi |

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

**Status saat ini: 389 tests passing** ✅ (mencakup config, database, streamer volume tracker, analyzer, notifier (termasuk status aman tanpa token + runtime reconfigure + **WebhookDispatcher v2.8**: payload test/alert, masking URL, dispatch sukses/gagal/timeout via transport injeksi; **v2.9 retry/backoff** dengan attempts + duration_ms), AI module, security hardening, AlertSystem data-driven dengan persistensi DB, BacktestEngine dengan harga riil, rate limiter per-IP, dan seluruh endpoint FastAPI termasuk anomalies, symbols, symbol detail, alerts rules persisten, alert history + **filter symbol/hours v2.6** + **priority v2.9**, heat map agregasi + **CSV export v2.6**, retensi + prune manual, **runtime settings GET/PUT v2.6** (validasi, clamp, enkripsi token, penolakan token tanpa chat id), **PWA manifest & ikon**, **rule-stats + export/import rules JSON v2.7**, **webhook channel + bulk edit rules v2.8** (validasi format URL, persist terenkripsi, masking scheme://host, status per-item bulk, pipeline alert-callback-webhook dispatch), **webhook delivery log + settings export/import v2.9** (secret-safe: plaintext ditolak, blob enc:v1 tervalidasi kunci), **webhook outbox + replay + health + rule-stats harian v2.10**, loop housekeeping retensi yang membaca **override runtime** (kini juga prune delivery log + outbox), dan **regression guard selector CSS atribut hidden bentuk valid + wajib rule author [hidden] utk elemen flex + tolak unicode escape korup (v2.7-v2.10)**).

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

### ✨ v2.2 — Market Pulse, Theme System & Hardening
- **📈 Market Pulse panel** — sparkline harga SVG per-symbol (top 4 symbol paling aktif) dengan trend badge naik/turun, harga terakhir & rata-rata spike (endpoint `/api/symbols` + `/api/sparkline/{symbol}` baru)
- **🌗 Dark/Light theme toggle** — CSS variables penuh, persist di `localStorage`, otomatis mengikuti `prefers-color-scheme`, shortcut keyboard `T`
- **🔢 Animated counters** — angka statistik beranimasi count-up (easeOutCubic) setiap update
- **🔔 Toast notifications** — feedback ringan untuk refresh, export, audit, anomaly & signal baru
- **⚠️ Error banner interaktif** — muncul otomatis saat API/DB gagal dengan tombol Retry & Dismiss (tidak lagi error diam-diam di console)
- **🎛️ Filter symbol interaktif** — dropdown untuk memfilter tabel anomali per-symbol (terisi otomatis dari `/api/symbols`)
- **⌨️ Keyboard shortcuts** — `R` refresh, `T` theme, `A` auto-refresh (hint di footer)
- **🔐 Opt-in API key auth** — set `DASHBOARD_API_KEY` untuk melindungi semua endpoint `/api/*` dengan header `X-API-Key` (constant-time compare); default nonaktif untuk penggunaan lokal
- **+16 test baru** — symbols, sparkline (normalisasi uppercase & clamp points), API key auth (401/200), error terstruktur, dan method DB baru → total **103 tests**

### ✨ v2.10 — Webhook Outbox & Replay, Delivery Health, 7-Day Audit, URL Filter State
- **📮 Webhook outbox (delivery gagal total tidak hilang lagi)** — alert yang gagal terkirim setelah semua percobaan retry kini masuk antrean persisten di tabel baru `webhook_outbox` (payload alert JSONB + rule/symbol + attempts + last_reason); di-replay **otomatis** oleh loop background tiap 5 menit (batch 20, siklus pertama 30 detik setelah start — antrean bertahan restart) atau **manual** via tombol **↻ Replay** di panel Outbox / aksi palette; sukses replay menghapus antrean + mencatat delivery log event `replay`, gagal tetap antre dengan counter attempts naik; endpoint `GET /api/webhook/outbox` (metadata saja — payload tidak pernah bocor ke dashboard) + `POST /api/webhook/outbox/replay` (maks 50 per panggilan, ringkasan sent/failed/remaining); antrean ikut di-prune bersama retensi alert_history agar basi tidak menumpuk
- **♥️ Delivery health 24 jam** — kartu kesehatan di Webhook Channel: **success rate** (progress bar gradien merah→hijau dengan transisi animasi + warna nilai good/warn/bad), **delivered 24h**, **avg latency (ms)**, **avg attempts** — endpoint `GET /api/webhook/health` (agregasi satu-pass SQL atas `webhook_deliveries`, termasuk `outbox_pending`; fallback hasil terakhir in-memory saat DB down); kartu auto-refresh setelah test send & replay
- **📈 Audit window 24h/7d** — segmented control baru di header Alert Rules: mode **7d** mengambil agregasi per-HARI via `?bucket=day` (`get_alert_rule_stats_daily`, 7 slot hari zero-filled, clamp 1..30) sehingga sparkline mingguan tetap terbaca (168 slot jam terlalu padat); label meta pakai chip `.win-tag` (7d/24h) tanpa duplikasi teks; tooltip bar menampilkan tanggal (MM-DD) di mode harian
- **🔗 URL filter state (shareable)** — filter Alert History kini tersinkron ke URL query (`?priority=high&q=pepe`) via `history.replaceState` (tanpa spam history); reload/link share langsung memulihkan filter sebelum data dimuat — koordinasi prioritas server-side + pencarian client-side tetap berjalan
- **🔧 Perbaikan test versi semver** — test lama membandingkan versi app sebagai STRING (`"2.10.0" >= "2.7.0"` = False secara leksikografis!) — kini di-parse ke tuple int agar bump versi 2-digit tidak mematahkan test
- **🎨 Styling** — chip kesehatan dengan grid auto-fit + hover lift + tabular-nums, outbox panel border dashed amber + badge count + baris border-left amber (tanda antre) + tombol Replay mini dengan state disabled selama mengirim, seg control rounded dengan state aktif cyan + aria-pressed, layout mobile 2-kolom utk grid kesehatan + stack baris outbox, rule author `[hidden]` utk elemen flex/grid baru (guard regresi), footer v2.10
- **+42 test baru** — DB outbox (enqueue + serialisasi JSON + truncation + clamp attempts, oldest-first + clamp limit, count, delete ANY($1), record attempt, prune 0-hari noop), DB health (parse agregasi + empty window + clamp 720), rule-stats harian (date_trunc day + clamp 30), endpoint rule-stats bucket=day (zero-fill 7 slot, key `day`, clamp 99→30, bucket invalid → hour, default hour unchanged), health endpoint (database + outbox_pending, fallback memory, nilai negatif di-clamp), outbox endpoint (shape tanpa payload leak), replay (not_configured, kosong, sukses → hapus + log event replay, mixed → gagal tetap antre + attempts naik + reason terakhir), pipeline (dispatch gagal → enqueue outbox dgn payload utuh, sukses → skip, replay loop sukses/gagal, not_configured noop, retensi prune outbox), guard HTML v2.10 (elemen, rule author hidden, wiring init restore-URL-sebelum-load, palette, unicode, footer) → total **389 tests**

### ✨ v2.9 — Webhook Delivery Log & Retry, History Search/Filter, Settings Export/Import
- **🧾 Webhook delivery log (DB)** — setiap hasil pengiriman webhook (test manual maupun alert nyata) kini dicatat ke tabel baru `webhook_deliveries` (event, ok, status code, reason, jumlah attempts, durasi ms, rule, symbol — persisten, tahan restart, di-prune otomatis bersama retensi alert_history); endpoint `GET /api/webhook/deliveries?limit=1..200` (fallback in-memory saat DB down); UI panel **Delivery log** collapsible di Webhook Channel: titik status hijau/merah, chip event TEST/ALERT, kode status mono berwarna, detail attempts • durasi • symbol • rule, waktu relatif, counter badge, custom scrollbar, layout wrap di mobile
- **🔁 Retry + backoff** — `WebhookDispatcher` kini mencoba ulang pengiriman gagal hingga `max_attempts` (default 3, clamp 1..5) dengan jeda backoff linear (`backoff_seconds * attempt`); hasil dispatch mencatat `attempts` + `duration_ms`; sukses di percobaan mana pun berhenti seketika — kegagalan webhook tetap tidak pernah memengaruhi pipeline alert
- **🔍 Filter & pencarian Alert History** — input **search** (client-side, debounce 160ms) menyaring item yang sudah dirender berdasarkan symbol/rule, tombol clear muncul saat aktif, empty state khusus "No alerts match"; dropdown **priority** (all/high/medium/low) memfilter server-side via `?priority=` (dicocokkan `LOWER(priority)` sehingga data lama `HIGH` maupun baru `high` sama-sama cocok); filter live juga berlaku untuk alert baru yang masuk via WebSocket
- **🧩 Settings export/import (full backup)** — tombol **Export** mengunduh SEMUA runtime settings sebagai JSON (`zcapital_settings_<stamp>.json`): int bernilai efektif, secret **hanya sebagai blob terenkripsi `enc:v1`** (plaintext tidak pernah keluar — file aman disimpan/dibagikan); tombol **Import** + modal (file picker atau paste JSON) menjalankan restore dengan status per-item: `applied`/`secret_applied`/`rejected` (secret plaintext ditolak eksplisit) /`undecryptable` (blob kunci instance lain) /`invalid_value`/`unknown_key`; webhook_url langsung dipasang ke dispatcher runtime, telegram config tersimpan dan diterapkan saat startup berikutnya (tanpa verifikasi jaringan saat import)
- **🐛 Fix unicode escape korup (sejak v2.8, terlihat via QA visual)** — 3 escape `\ud83d\dd25` (kehilangan `u`) membuat judul **Alert Heat Map** tampil literal "dd25" (EN/ID) dan ikon palette "Export heat map CSV" rusak; diperbaiki + guard test baru yang memindai seluruh HTML dan menolak escape `\u` tidak valid agar kelas korupsi tooling ini tidak lolos lagi
- **🎨 Styling** — panel delivery log dengan border rounded + header hover + caret rotasi + scrollbar tipis cyan, baris delivery dengan dot glow + chip event uppercase + kode mono berwarna (hijau/merah), search input dengan ikon + focus-ring cyan + tombol clear inline, select priority konsisten dengan filter-select lain, tombol Export/Import di toolbar System Settings (stack di mobile), modal import settings reuse pattern rules import, footer v2.9
- **+39 test baru** — DB delivery log (insert + truncation + clamp limit + prune + parse DELETE), filter priority SQL, dispatcher retry (sukses langsung, sukses setelah retry, gagal habis percobaan, clamp max_attempts, not_configured attempts=0), endpoint deliveries (empty, serialisasi timestamp, fallback memory tanpa bocor URL), test-send tercatat ke DB, history priority endpoint (valid/invalid/combined), export (shape + attachment + tanpa plaintext + secret belum persist tidak ikut + nilai int efektif), import (ints applied + persist, unknown/invalid, **plaintext secret ditolak**, blob enc:v1 applied + dispatcher terpasang, blob rusak undecryptable, **roundtrip export-import-restore**, kosong 422), pipeline alert-dispatch-delivery log, retensi ikut prune delivery log, guard HTML v2.9 (elemen, wiring, i18n, footer, rule [hidden] flex, **tolak unicode escape korup**) → total **347 tests**

### ✨ v2.8 — Webhook Alert Channel, Bulk Edit Rules & Sparkline Tooltip
- **🔗 Channel notifikasi webhook** — alert ter-trigger kini bisa dikirim sebagai JSON POST ke endpoint HTTP arbitrary: `WebhookDispatcher` di `app/notifier.py` (timeout ketat 10s, hasil `{ok, status_code, reason}`, TIDAK pernah raise — kegagalan webhook tidak pernah memengaruhi pipeline utama), dipanggil fire-and-forget dari callback alert (`main._broadcast_alert`); URL dikonfigurasi via runtime settings (`webhook_url`, write-only + **terenkripsi Fernet**, tervalidasi format http/https + host saat apply), di-restore otomatis saat restart (best-effort); payload `{source, type: alert.triggered|alert.test, timestamp, alert:{rule, priority, symbol, channels, data}}` + header `X-ZCapital-Event`; UI panel Webhook Channel di Notification Settings (chip endpoint tersamarkan **scheme://host** — path sering berisi token rahasia, chip hasil delivery terakhir, form apply, tombol Send Test Payload), endpoint `GET /api/webhook/status` + `POST /api/webhook/test`; aksi palette "Send webhook test payload"
- **✅ Bulk edit alert rules** — checkbox per rule editable + select-all (indeterminate di tengah) + bulk bar animasi: terapkan SATU threshold ke banyak rule sekaligus via `POST /api/alerts/rules/bulk` (1..50 nama, status per-item konsisten dgn import: `updated`/`unknown`/`not_editable`/`invalid_name`, NaN/Infinity/negatif ditolak 400, gagal persist DB tetap update in-memory dengan flag `persisted:false`); Enter di input = apply; toast ringkasan `N/M rule(s) -> threshold X`; aksi palette "Apply bulk threshold"
- **💡 Sparkline tooltip custom** — tooltip mengambang menggantikan title native (tampil seketika, auto-hide 2.5s, hilang saat mouse leave/scroll, posisi clamp ke viewport); bar sparkline kini punya hover effect (fill-opacity 1) + `role=img` + `aria-label` per bar utk screen reader
- **🐟 Fix bug CSS [hidden] vs display:flex (QA visual)** — bulk bar & select-all wrap memakai `display:flex` yang MENIMPA rule UA `[hidden]{display:none}` sehingga tetap tampil walau atribut hidden terpasang (bulk bar "0 selected" selalu tampak); diperbaiki dgn rule author `.bulk-bar[hidden]`/`.select-all-wrap[hidden] {display:none}` + guard test baru mewajibkan elemen flex punya rule `[hidden]` level author — kelas regresi yang sama dgn bug backdrop modal v2.3, kali ini tertangkap sebelum push berkat screenshot QA
- **🎨 Styling** — rule row hover (border accent + shadow lembut, transisi 0.18s) + state `.selected` (border + latar cyan tipis, versi light theme), checkbox custom accent-color + `focus-visible` ring, bulk bar dashed accent + animasi bulkIn + layout stack di mobile, section webhook dengan divider dashed + chip status ok/warn konsisten dgn panel Telegram, footer v2.8
- **+42 test baru** — WebhookDispatcher (payload test/alert + header, masking URL tidak bocor, dispatch 2xx/5xx/timeout/connection-refused/not-configured via `httpx.MockTransport`), spec + masking settings, endpoint status/test (belum/benar terkonfigurasi, transport injeksi), PUT webhook_url (apply + persist terenkripsi + cache, tolak scheme invalid/tanpa host), GET settings masked, bulk endpoint (2 rule sukses + persist, mixed status, NaN/Infinity raw-body -> 400, negatif -> 400, kosong/51 nama -> 422, whitespace -> invalid_name, persist gagal -> tetap update memori), **pipeline alert->callback->webhook dispatch** (fire-and-forget verified), guard HTML v2.8 (bulk bar, webhook section, tooltip, selector [hidden] flex) -> total **308 tests**

### ✨ v2.7 — Rule Audit Sparkline, Import/Export Rules, Command Palette & i18n
- **📊 Audit sparkline per-rule** — setiap baris di panel Alert Rules kini menampilkan mini bar chart 24 jam (endpoint `/api/alerts/rule-stats?hours=1..168`: agregasi per-rule per-jam dari `alert_history`, slot jam kosong diisi 0) + meta jumlah fire/24h + waktu fire terakhir relatif; rules tanpa data tampil "no fire data"
- **📋 Export/Import rules JSON** — tombol JSON mengunduh seluruh konfigurasi rules (`GET /api/alerts/rules/export`, attachment ber-timestamp); modal Import menerima paste JSON atau file .json (full export object, bare array, atau `{rules:[…]}`) → `POST /api/alerts/rules/import` update + persist threshold rule editable secara bulk dengan status per-item (`updated`/`unknown`/`not_editable`/`invalid_threshold`) — satu item jelek tidak menggagalkan batch, threshold negatif/NaN/Infinity ditolak per-item, gagal persist DB tetap mengubah state in-memory dengan flag `persisted:false`
- **⌘ Command Palette (Ctrl+K)** — overlay pencarian perintah ala editor: 15+ aksi (refresh, theme, auto-refresh, reload rules/history/settings, maintenance panels, Telegram test, browser notifications, export CSV signals/heatmap/rules JSON, import rules, security audit, toggle bahasa, filter anomali per-symbol dinamis) dengan filter substring, navigasi ↑↓ + Enter + Esc, ikon per-aksi + hint shortcut, animasi paletteIn, tombol ⌘K di header; shortcut `L` toggle bahasa
- **🌐 i18n ID/EN** — toggle bahasa Indonesia/English untuk 13+ label statis (judul semua panel, hint rules, teks modal import) via atribut `data-i18n` + kamus `I18N`; persist di `localStorage` (`oracle-lang`), judul dokumen ikut berubah, tombol 🌐 di header + shortcut `L` + aksi palette
- **🐛 Fix dead-code CSS korup (root-cause v2.3)** — 3 selector atribut hidden (`.error-banner`, `.modal-backdrop`, `.offline-banner`) tercatat korup sejak v2.3 (kehilangan karakter pembuka atribut) sehingga rule tidak pernah valid; guard lama justru menegaskan bentuk korup. Di browser modern tak terasa (UA rule display:none !important menutup), tetapi kini diperbaiki ke bentuk valid + guard test ditulis ulang mewajibkan bentuk valid & menolak korup
- **🎨 Styling** — bar sparkline dengan opacity proporsional + tooltip per-bar, layout rule-row 3 kolom (info/audit/threshold) yang stack rapi di mobile, textarea mono untuk import dengan status berwarna ok/err, palette item hover + active outline, footer v2.7 dengan hint Ctrl K & L
- **+27 test baru** — DB rule-stats (SQL GROUP BY + clamp), endpoint rule-stats (pengisian bucket, urutan, clamp 1..168, error terstruktur), export (attachment + shape tanpa lambda + refleksi threshold runtime), import (bulk sukses + persist, mixed status, NaN/Infinity raw-body, nama whitespace, 422 missing/empty/name-too-long, roundtrip export→import, persist gagal tetap update memori), guard HTML v2.7 (elemen baru, wiring data-i18n, selector valid) → total **266 tests**

### ✨ v2.6 — Runtime Settings, Click-to-Filter, Browser Notifications & PWA
- **⚙️ Panel System Settings** — ubah konfigurasi runtime langsung dari dashboard tanpa restart: `alert_history_retention_days`, `dashboard_refresh_seconds` (interval auto-refresh berubah live), `anomaly_feed_limit` (ukuran feed anomali). Nilai tersimpan di tabel `app_settings` (survive restart), badge **override** untuk nilai ≠ default, validasi int dengan clamp + warning toast, endpoint `GET/PUT /api/settings` (terproteksi API key + rate limit)
- **🔐 Konfigurasi Telegram runtime** — form chat id + bot token (write-only password field) di panel Notification Settings: token diverifikasi ke API Telegram (`get_me`) sebelum dipasang ke notifier yang berjalan (`notifier.reconfigure()` — state lama dipertahankan bila token invalid), lalu disimpan **terenkripsi Fernet** (kunci derivasi dari `DASHBOARD_SECRET_SALT` atau `DATABASE_URL`) dan di-restore otomatis saat restart (best-effort — startup tidak pernah gagal karena Telegram down). Chat id tanpa token ditolak; token invalid TIDAK dipersist agar DB tidak berisi token mati
- **🖱️ Heat map click-to-filter** — klik label symbol (all-time) atau sel ber-alert (symbol + window jam) di heat map → panel Alert History terfilter otomatis dengan chip cyan "Filter: PEPEUSDT • ≤ 24h" yang bisa diklik untuk reset; endpoint history mendukung `?symbol=` & `?hours=`
- **🔔 Browser notifications** — toggle switch di Notification Settings (Notification API): izin dikelola dengan rapi (default/denied/granted), preferensi persist di localStorage, alert `alert_triggered` via WebSocket memunculkan desktop notification (judul prioritas + symbol + spike/harga, klik fokus ke tab), degradasi graceful di browser tanpa dukungan; shortcut `N`
- **📡 Offline indicator** — banner amber "You're offline" otomatis via event `offline`/`online` browser (dicek native via `agent-browser set offline`), kembali online → toast + auto refresh semua panel
- **📱 PWA** — manifest `/dashboard/manifest.webmanifest` + ikon PNG 192/512 + favicon + apple-touch-icon + `theme-color`: dashboard bisa di-install ke homescreen sebagai standalone app
- **⬇️ Export CSV heat map** — tombol CSV di panel heat map → `GET /api/alerts/heatmap.csv?hours=` (kolom symbol/hour/alert_count/severity)
- **⌨️ Shortcut `S`** — reload + scroll ke System Settings (footer v2.6)
- **🐛 Fix bug kritis QA** — selector CSS ter-korupsi `.error-banneridden]` / `.modal-backdropidden]` (kehilangan `[h`) sejak ronde sebelumnya: atribut `hidden` kalah oleh `display:flex` → **backdrop modal transparan (inset 0, z-index 200) selalu menutupi halaman dan memblokir SEMUA klik mouse asli**, plus banner error/offline selalu tampil. Diperbaiki + regression guard test (`TestDashboardHtmlIntegrity`) agar tidak terulang; diverifikasi QA klik mouse real (bukan eval-click) bekerja normal
- **+50 test baru** — DB app_settings CRUD + filter history, enkripsi/dekripsi secret, validasi/clamp, cache override, payload GET tanpa kebocoran secret, notifier.reconfigure (sukses/invalid token menjaga state lama/tanpa token di hasil), endpoint settings (shape, override, clamp persist, unknown key, token apply+encrypt, token invalid tidak persist, token tanpa chat ditolak), history filter endpoint, heatmap.csv, manifest, ikon, retensi efektif dari override, restore Telegram startup, guard HTML → total **239 tests**

### ✨ v2.5 — Heat Map Agregasi, Retensi Otomatis & Panel Notifikasi
- **🔥 Alert Heat Map** — agregasi alert per-symbol per-jam dari DB (endpoint `/api/alerts/heatmap?hours=6..168`): grid sel berwarna intensitas merah (semakin banyak alert semakin pekat), label severity per-symbol (HIGH merah / MEDIUM amber), total per-symbol, sumbu waktu (-6h … now), summary chips (Σ alerts + top symbol), legend gradient, window selector 12/24/48/72 jam, scroll horizontal di mobile, tooltip per-sel, auto-refresh ikut polling 30s
- **🧹 Data Retention otomatis** — loop background menghapus `alert_history` lebih tua dari `ALERT_HISTORY_RETENTION_DAYS` (default 7 hari, 0 = off) setiap `ALERT_RETENTION_INTERVAL_MINUTES` (default 60 menit); DB method `prune_alert_history()` parse jumlah terhapus dari status asyncpg; hasil prune terakhir tampil di panel retention; error DB tidak pernah mematikan loop
- **🧹 Panel Data Retention di dashboard** — 4 stat box (retention days / prune interval / stored alerts / last prune), umur baris tertua, tombol **Prune Now** (POST `/api/alerts/prune`, body `{"days": 1..365}` opsional dengan fallback pengaturan) + toast hasil + refresh otomatis heat map & history
- **📨 Notification Settings panel** — status chip Bot (@username), Chat ID (**disamarkan** `••••6789`), dan Database; tombol **Send Test Message** (POST `/api/telegram/test`) dengan loading state + toast hasil; **token TIDAK PERNAH dikirim ke browser** — endpoint hanya mengekspos metadata (metode `TelegramNotifier.get_status()`)
- **Endpoint baru** (semua terproteksi API key + rate limit): `GET /api/alerts/heatmap`, `GET /api/alerts/retention`, `POST /api/alerts/prune`, `GET /api/telegram/status`, `POST /api/telegram/test` — gagal kirim test dianggap HASIL (flag `sent` + `reason`), bukan error endpoint
- **⌨️ Shortcut `M`** — refresh panel maintenance (heat map + retention + status Telegram) dari keyboard (footer v2.5)
- **+31 test baru** — DB layer (prune parse status DELETE n / clamp window / stats), notifier status (masking chat id, tanpa token), endpoint heat map (grouping, sorting, clamp, error terstruktur), retention (default / degradasi DB / prune manual + fallback / validasi 422), Telegram (tanpa notifier / not configured / sukses / send failed / exception), loop retensi (disabled / record result / survive DB error / periodik) → total **189 tests**

### ✨ v2.4 — Persistensi Alert & Real-time Alert Pipeline
- **🔌 Alert rules survive restart** — tabel `alert_rules` di PostgreSQL: threshold yang diubah via dashboard di-upsert ke DB (`PUT` response flag `persisted`) dan otomatis di-restore saat proses start ulang (`AlertSystem.load_persisted_rules`, best-effort — DB mati pun rules tetap jalan dengan default)
- **🗄️ Alert history persisten** — tabel `alert_history` (rule, priority, symbol, data JSONB): setiap alert ter-trigger tersimpan ke DB; endpoint `/api/alerts/history` kini membaca dari DB (flag `source: database`) dengan fallback in-memory (`source: memory`) bila DB tidak tersedia
- **🚨 Alert History panel di dashboard** — kartu alert berwarna prioritas (HIGH merah / MEDIUM amber), ikon prioritas, symbol + rule + channel chips, metrik spike/confidence/price, waktu relatif ("18m ago") + absolut, badge sumber data (database/in-memory), tombol Refresh + shortcut `H`, animasi entrance untuk item baru, max-height scroll
- **⚡ Pipeline alert kini hidup** — fix gap integrasi: `AlertSystem.check_alerts()` **tidak pernah dipanggil** di pipeline utama (rules ada tapi tak pernah dievaluasi). Kini `_handle_anomaly` mengevaluasi rules terhadap setiap hasil analisis → trigger di-persist ke DB → di-broadcast real-time
- **📡 WebSocket `alert_triggered`** — alert yang ter-trigger langsung didorong ke semua dashboard client: toast prioritas HIGH (error) / lainnya (warn), log entry, dan item history baru masuk otomatis dengan animasi (tanpa refresh)
- **⌨️ Shortcut `H`** — refresh Alert History dari keyboard (hint di footer v2.4)
- **+21 test baru** — persistensi rules/history DB (upsert, JSONB parse, clamp), AlertSystem (load/persist/callback, best-effort DB failure), endpoint history (database + fallback memory), integrasi pipeline (anomaly → alert → broadcast WS, pipeline tetap jalan saat alert engine error) → total **158 tests**

### ✨ v2.3 — Symbol Detail Modal, Backtest Engine & Alert Rules
- **🔍 Symbol detail modal** — klik Market Pulse card (atau tekan Enter) membuka modal detail: chart harga besar (SVG 700×240) dengan grid, label axis harga & waktu, marker high/low, gradient area, crosshair + tooltip hover, chips Open/Close/High/Low/Change, dan tabel 20 anomali terakhir symbol tersebut (endpoint `/api/symbol/{symbol}` baru, 404 untuk symbol tak dikenal)
- **⚡ Strategy Backtest interaktif** — panel backtest dalam modal: pilih lookback (1–90 hari) & ambang spike (10–10000%), hasil metrik Signals / Win Rate / Total Return / Avg Trade / Sharpe / Max Drawdown + tabel trade dengan PnL per-trade (endpoint `POST /api/backtest/{symbol}`)
- **🐛 Fix BacktestEngine** — (1) `ZeroDivisionError` saat entry price 0/None (sekarang di-skip), (2) exit price placeholder "+5% selalu" yang membuat win rate selalu 100% → kini exit dihitung dari **harga riil** price history pada horizon holding, trade tanpa data harga setelahnya tidak dievaluasi agar metrik jujur
- **🔔 Alert Rules panel** — lihat & ubah threshold rule alert langsung dari dashboard (badge prioritas HIGH/MEDIUM, channel chips, input threshold + Save dengan toast konfirmasi). `AlertSystem` direfactor data-driven: threshold editable via `PUT /api/alerts/rules/{name}`, rule `confirmed_signal` kini benar-benar mewajibkan `confirmed=True` (+ field `requires`), lambda tidak pernah bocor ke JSON API
- **🚦 Rate limiting per-IP** — sliding window in-memory (default 120 req/menit per endpoint, `DASHBOARD_RATE_LIMIT` / `DASHBOARD_RATE_LIMIT_WINDOW`), HTTP 429 + header `Retry-After`, anti memory-bloat (evict stale IP, cap 10k IP), hormati `X-Forwarded-For`
- **🎨 Styling & UX** — animasi modal (fade + scale, hormati `prefers-reduced-motion`), pulse card klikable dengan hover lift & hint "Click for details", prioritas badge & channel chips, Escape menutup modal, klik backdrop menutup, focus management, layout mobile modal responsif
- **+34 test baru** — rate limiter (unit + HTTP 429), alerts rules endpoints (404/400/422), symbol detail (uppercase, 404, error terstruktur), backtest (harga riil, horizon exit, skip price ≤ 0), AlertSystem data-driven → total **137 tests**

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
