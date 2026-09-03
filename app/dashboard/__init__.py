"""
Dashboard & Observability Module for Crypto Oracle AI
Real-time dashboard, alerting system, and backtesting engine
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable, Awaitable
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class RealTimeDashboard:
    """
    Provides real-time metrics and status for the monitoring system
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.metrics_buffer: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.max_buffer_size = 1000
    
    async def start(self) -> None:
        """Initialize the dashboard"""
        logger.info("Real-Time Dashboard initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Real-Time Dashboard stopped")
    
    def record_metric(self, metric_type: str, data: Dict[str, Any]) -> None:
        """Record a metric point"""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        metric = {
            'timestamp': timestamp,
            'data': data
        }
        
        self.metrics_buffer[metric_type].append(metric)
        
        # Trim buffer if too large
        if len(self.metrics_buffer[metric_type]) > self.max_buffer_size:
            self.metrics_buffer[metric_type] = self.metrics_buffer[metric_type][-self.max_buffer_size:]
    
    async def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard data
        
        Returns:
            Dashboard metrics and status
        """
        try:
            # Get recent anomalies from database
            recent_anomalies = await self.db.get_recent_anomalies(limit=50)
            
            # Calculate statistics
            total_anomalies_24h = len(recent_anomalies)
            symbols_monitored = set(a['symbol'] for a in recent_anomalies) if recent_anomalies else set()
            
            # Average volume spike
            avg_volume_spike = 0.0
            if recent_anomalies:
                spikes = [a['volume_spike'] for a in recent_anomalies if a.get('volume_spike')]
                if spikes:
                    avg_volume_spike = sum(spikes) / len(spikes)
            
            # Get signals sent
            signals_sent = len([a for a in recent_anomalies if a.get('volume_spike', 0) > 300])
            
            dashboard = {
                'status': 'running',
                'uptime': self._get_uptime(),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'summary': {
                    'total_anomalies_24h': total_anomalies_24h,
                    'symbols_monitored': len(symbols_monitored),
                    'avg_volume_spike': avg_volume_spike,
                    'signals_sent': signals_sent
                },
                'recent_anomalies': recent_anomalies[:20],  # Last 20
                'top_symbols': self._get_top_symbols(recent_anomalies),
                'system_health': await self._get_system_health()
            }
            
            return dashboard
            
        except Exception as e:
            logger.error(f"Error getting dashboard data: {e}")
            return {'error': str(e)}
    
    def _get_uptime(self) -> str:
        """Calculate system uptime"""
        # Would track actual start time in production
        return "Running"
    
    def _get_top_symbols(
        self,
        anomalies: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get most active symbols"""
        symbol_counts = defaultdict(int)
        symbol_spikes = defaultdict(list)
        
        for anomaly in anomalies:
            symbol = anomaly.get('symbol', 'UNKNOWN')
            symbol_counts[symbol] += 1
            if anomaly.get('volume_spike'):
                symbol_spikes[symbol].append(anomaly['volume_spike'])
        
        top_symbols = []
        for symbol, count in sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            spikes = symbol_spikes[symbol]
            avg_spike = sum(spikes) / len(spikes) if spikes else 0
            
            top_symbols.append({
                'symbol': symbol,
                'anomaly_count': count,
                'avg_volume_spike': avg_spike,
                'max_spike': max(spikes) if spikes else 0
            })
        
        return top_symbols
    
    async def _get_system_health(self) -> Dict[str, Any]:
        """Get system health metrics"""
        return {
            'database': 'connected',
            'websocket': 'active',
            'telegram': 'configured' if self.settings.telegram_bot_token else 'not_configured',
            'etherscan': 'configured' if self.settings.etherscan_api_key else 'not_configured',
            'cryptopanic': 'configured' if self.settings.cryptopanic_api_key else 'not_configured'
        }


class AlertSystem:
    """
    Advanced alerting system with multiple notification channels
    """

    # Tipe callback: async def cb(alert: Dict) -> None; dipanggil untuk
    # tiap alert yang ter-trigger (mis. broadcast WebSocket ke dashboard).
    AlertCallback = Callable[[Dict[str, Any]], Awaitable[None]]

    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.alert_rules: List[Dict[str, Any]] = []
        self.alert_history: List[Dict[str, Any]] = []
        self.rate_limits: Dict[str, datetime] = {}
        self.on_alert: Optional[AlertSystem.AlertCallback] = None

    def set_alert_callback(self, callback: AlertCallback) -> None:
        """Pasang async callback yang dipanggil tiap alert ter-trigger.

        Dipakai main.py untuk mem-broadcast alert ke dashboard secara
        real-time via WebSocket.
        """
        self.on_alert = callback

    async def start(self) -> None:
        """Initialize the alert system (muat default + persistensi DB)."""
        self._load_default_rules()
        await self.load_persisted_rules()
        logger.info("Alert System initialized")

    async def load_persisted_rules(self) -> bool:
        """Terapkan threshold tersimpan di DB ke rules editable.

        v2.4: perubahan threshold lewat dashboard kini survive restart.
        Best-effort: bila DB gagal/tabel belum ada, rules tetap jalan
        dengan default dan method mengembalikan False.
        """
        try:
            persisted = await self.db.get_alert_rule_thresholds()
        except Exception as e:
            logger.warning(f"Could not load persisted alert rules: {e}")
            return False

        applied = 0
        for rule in self.alert_rules:
            if rule.get("editable") and rule["name"] in persisted:
                try:
                    rule["threshold"] = float(persisted[rule["name"]])
                    applied += 1
                except (TypeError, ValueError):
                    continue
        if applied:
            logger.info(f"Restored {applied} persisted alert rule threshold(s)")
        return True

    async def persist_rule_threshold(self, name: str, value: float) -> bool:
        """Simpan threshold rule ke DB agar survive restart (best-effort)."""
        try:
            await self.db.upsert_alert_rule_threshold(name, float(value))
            return True
        except Exception as e:
            logger.warning(f"Could not persist alert rule '{name}': {e}")
            return False
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Alert System stopped")
    
    def _load_default_rules(self) -> None:
        """Load default alert rules.

        Rules bersifat data-driven agar bisa dibaca/diubah lewat API
        dashboard (GET/PUT /api/alerts/rules):
        - Rule dengan 'threshold_key' + 'threshold' -> kondisi numerik
          (x[threshold_key] > threshold) dan threshold-nya editable.
        - Rule dengan 'condition' lambda -> kondisi kustom non-editable.
        """
        self.alert_rules = [
            {
                'name': 'extreme_volume_spike',
                'description': 'Volume spike melebihi batas persentase',
                'threshold_key': 'volume_spike',
                'threshold': 500.0,
                'priority': 'HIGH',
                'channels': ['telegram', 'log'],
                'editable': True,
            },
            {
                'name': 'smart_money_detected',
                'description': 'Smart money wallet terdeteksi pada token',
                'condition': lambda x: x.get('smart_money_detected', False),
                'priority': 'HIGH',
                'channels': ['telegram', 'log'],
                'editable': False,
            },
            {
                'name': 'positive_news_sentiment',
                'description': 'Sentimen berita positif',
                'condition': lambda x: x.get('news_sentiment') == 'positive',
                'priority': 'MEDIUM',
                'channels': ['telegram'],
                'editable': False,
            },
            {
                'name': 'confirmed_signal',
                'description': 'Sinyal terkonfirmasi dengan confidence di atas batas',
                'threshold_key': 'confidence_score',
                'threshold': 0.7,
                'requires': ['confirmed'],
                'priority': 'HIGH',
                'channels': ['telegram', 'log'],
                'editable': True,
            },
        ]

    def _rule_matches(self, rule: Dict[str, Any], data: Dict[str, Any]) -> bool:
        """Evaluasi satu rule terhadap data analisis.

        - threshold_key -> bandingkan nilai numerik dengan threshold ('>').
        - Tanpa threshold_key -> pakai lambda 'condition'.
        - 'requires' -> field tambahan yang HARUS truthy (mis. confirmed).
        """
        threshold_key = rule.get('threshold_key')
        if threshold_key:
            threshold = float(rule.get('threshold', 0) or 0)
            try:
                value = float(data.get(threshold_key, 0) or 0)
            except (TypeError, ValueError):
                return False
            matched = value > threshold
        else:
            condition = rule.get('condition')
            matched = bool(condition(data)) if condition else False

        if not matched:
            return False
        for required in rule.get('requires', []):
            if not data.get(required):
                return False
        return True

    def get_rules(self) -> List[Dict[str, Any]]:
        """Representasi rules yang aman untuk dikirim via JSON API.

        Lambda condition tidak ikut diserialisasi; yang dikirim adalah
        metadata + threshold sehingga UI bisa menampilkannya.
        """
        return [
            {
                'name': rule['name'],
                'description': rule.get('description', ''),
                'priority': rule['priority'],
                'channels': list(rule.get('channels', [])),
                'editable': bool(rule.get('editable', False)),
                'threshold': rule.get('threshold'),
                'threshold_key': rule.get('threshold_key'),
                'requires': list(rule.get('requires', [])),
            }
            for rule in self.alert_rules
        ]

    def set_rule_threshold(self, name: str, value: float) -> Dict[str, Any]:
        """Ubah threshold rule yang editable.

        Raises:
            KeyError: rule tidak ditemukan.
            ValueError: rule tidak editable.
        """
        for rule in self.alert_rules:
            if rule['name'] == name:
                if not rule.get('editable', False):
                    raise ValueError(f"Rule '{name}' is not threshold-editable")
                rule['threshold'] = float(value)
                return {
                    'name': rule['name'],
                    'description': rule.get('description', ''),
                    'priority': rule['priority'],
                    'channels': list(rule.get('channels', [])),
                    'editable': True,
                    'threshold': rule['threshold'],
                    'threshold_key': rule.get('threshold_key'),
                }
        raise KeyError(name)
    
    async def check_alerts(self, analysis_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Check if any alert rules are triggered
        
        Returns:
            List of triggered alerts
        """
        triggered_alerts = []
        
        for rule in self.alert_rules:
            try:
                if self._rule_matches(rule, analysis_result):
                    # Check rate limiting
                    rule_name = rule['name']
                    symbol = analysis_result.get('symbol', 'UNKNOWN')
                    rate_key = f"{rule_name}:{symbol}"
                    
                    now = datetime.now(timezone.utc)
                    last_alert = self.rate_limits.get(rate_key)
                    
                    # Rate limit: max 1 alert per 5 minutes per rule per symbol
                    if last_alert and (now - last_alert).total_seconds() < 300:
                        continue
                    
                    # Create alert
                    alert = {
                        'timestamp': now.isoformat(),
                        'rule': rule_name,
                        'priority': rule['priority'],
                        'symbol': symbol,
                        'channels': rule['channels'],
                        'data': analysis_result
                    }
                    
                    triggered_alerts.append(alert)
                    self.rate_limits[rate_key] = now
                    self.alert_history.append(alert)

                    # v2.4: simpan ke DB (persisten, tahan restart) dan
                    # panggil callback (WS broadcast) - keduanya best-effort
                    # agar kegagalan notifikasi tidak memutus evaluasi rule.
                    try:
                        await self.db.log_alert(
                            rule=rule_name,
                            priority=rule['priority'],
                            symbol=symbol,
                            data=analysis_result,
                        )
                    except Exception as db_err:
                        logger.warning(f"Could not persist alert to DB: {db_err}")

                    if self.on_alert is not None:
                        try:
                            await self.on_alert(alert)
                        except Exception as cb_err:
                            logger.warning(f"Alert callback failed: {cb_err}")

                    logger.info(f"Alert triggered: {rule_name} for {symbol}")
                    
            except Exception as e:
                logger.error(f"Error checking alert rule {rule['name']}: {e}")
        
        return triggered_alerts
    
    def get_alert_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alert history"""
        return self.alert_history[-limit:]


class BacktestEngine:
    """
    Backtesting engine for testing strategies on historical data
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.backtest_results: List[Dict[str, Any]] = []
    
    async def start(self) -> None:
        """Initialize the backtest engine"""
        logger.info("Backtest Engine initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Backtest Engine stopped")
    
    async def run_backtest(
        self,
        symbol: str,
        days: int = 7,
        volume_threshold: float = 300.0
    ) -> Dict[str, Any]:
        """
        Run backtest on historical anomaly data
        
        Args:
            symbol: Token symbol to backtest
            days: Number of days to look back
            volume_threshold: Volume spike threshold percentage
        
        Returns:
            Backtest results with performance metrics
        """
        result = {
            'symbol': symbol,
            'period_days': days,
            'parameters': {
                'volume_threshold': volume_threshold
            },
            'total_signals': 0,
            'hypothetical_trades': [],
            'performance': {
                'win_rate': 0.0,
                'total_return': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0
            }
        }
        
        try:
            # Get historical anomalies
            anomalies = await self.db.get_recent_anomalies(
                symbol=symbol,
                limit=1000
            )

            # Riwayat harga kronologis (lama -> baru) untuk simulasi exit riil
            price_history = await self.db.get_price_history(symbol, limit=1000)
            result['data_points'] = len(price_history)

            # Filter by date range
            # CATATAN: asyncpg mengembalikan datetime timezone-aware untuk kolom
            # TIMESTAMPTZ. Bandingkan dengan datetime yang juga timezone-aware
            # agar tidak terjadi TypeError (naive vs aware).
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            filtered_anomalies = []
            for a in anomalies:
                ts = a.get('timestamp')
                if not ts:
                    continue
                ts_dt = self._to_aware_dt(ts)
                if ts_dt and ts_dt > cutoff_date:
                    filtered_anomalies.append((a, ts_dt))

            # Simulate trades on each signal
            hypothetical_pnl = []

            for anomaly, ts_dt in filtered_anomalies:
                spike = anomaly.get('volume_spike', 0) or 0
                try:
                    spike = float(spike)
                except (TypeError, ValueError):
                    continue
                if spike < volume_threshold:
                    continue

                # FIX bug lama: entry_price 0/None menyebabkan ZeroDivisionError
                try:
                    entry_price = float(anomaly.get('price', 0) or 0)
                except (TypeError, ValueError):
                    continue
                if entry_price <= 0:
                    continue

                # FIX bug lama: exit price placeholder (+5% selalu) membuat
                # win_rate selalu 100%. Sekarang pakai harga riil dari price
                # history pada horizon entry + holding_hours.
                exit_price = self._find_exit_price(
                    price_history, ts_dt,
                    horizon_minutes=int(self.settings.volume_window_minutes * 12)
                    if self.settings.volume_window_minutes > 0 else 60,
                )
                if exit_price is None:
                    # Tidak ada data harga setelah entry -> trade tidak bisa
                    # dievaluasi, jangan dimasukkan agar metrik jujur.
                    continue

                pnl_pct = ((exit_price - entry_price) / entry_price) * 100

                trade = {
                    'entry_time': str(anomaly.get('timestamp')),
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl_percent': pnl_pct,
                    'volume_spike': spike
                }

                result['hypothetical_trades'].append(trade)
                hypothetical_pnl.append(pnl_pct)
            
            result['total_signals'] = len(result['hypothetical_trades'])
            
            # Calculate performance metrics
            if hypothetical_pnl:
                winning_trades = [p for p in hypothetical_pnl if p > 0]
                
                result['performance']['win_rate'] = len(winning_trades) / len(hypothetical_pnl)
                result['performance']['total_return'] = sum(hypothetical_pnl)
                result['performance']['avg_trade_return'] = sum(hypothetical_pnl) / len(hypothetical_pnl)
                
                # Simplified Sharpe ratio (assuming risk-free rate = 0)
                if len(hypothetical_pnl) > 1:
                    import numpy as np
                    returns = np.array(hypothetical_pnl)
                    std_dev = np.std(returns)
                    if std_dev > 0:
                        result['performance']['sharpe_ratio'] = np.mean(returns) / std_dev
                
                # Max drawdown (simplified)
                cumulative = 0
                peak = 0
                max_dd = 0
                
                for pnl in hypothetical_pnl:
                    cumulative += pnl
                    if cumulative > peak:
                        peak = cumulative
                    drawdown = peak - cumulative
                    if drawdown > max_dd:
                        max_dd = drawdown
                
                result['performance']['max_drawdown'] = max_dd
            
            self.backtest_results.append(result)
            
        except Exception as e:
            logger.error(f"Error running backtest for {symbol}: {e}")
            result['error'] = str(e)
        
        return result
    
    @staticmethod
    def _to_aware_dt(value: Any) -> Optional[datetime]:
        """Konversi timestamp (datetime | str) menjadi datetime timezone-aware."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _find_exit_price(
        price_history: List[Dict[str, Any]],
        entry_ts: datetime,
        horizon_minutes: int = 60,
    ) -> Optional[float]:
        """Cari harga exit riil: titik harga terakhir dalam horizon waktu.

        Price history harus kronologis (lama -> baru). Return None bila
        tidak ada titik harga setelah entry (data tidak cukup).
        """
        if entry_ts is None:
            return None
        horizon_end = entry_ts + timedelta(minutes=horizon_minutes)
        exit_price: Optional[float] = None
        for point in price_history:
            point_ts = BacktestEngine._to_aware_dt(point.get('timestamp'))
            if point_ts is None or point_ts <= entry_ts:
                continue
            if point_ts > horizon_end:
                # Titik pertama setelah horizon = eksekusi terdekat setelah hold
                price = point.get('price')
                return float(price) if price is not None else exit_price
            price = point.get('price')
            if price is not None:
                exit_price = float(price)
        return exit_price

    def get_backtest_summary(self) -> Dict[str, Any]:
        """Get summary of all backtests run"""
        if not self.backtest_results:
            return {'total_backtests': 0}
        
        return {
            'total_backtests': len(self.backtest_results),
            'backtests': self.backtest_results[-5:]  # Last 5
        }
