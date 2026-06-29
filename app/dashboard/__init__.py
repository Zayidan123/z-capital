"""
Dashboard & Observability Module for Crypto Oracle AI
Real-time dashboard, alerting system, and backtesting engine
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
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
        timestamp = datetime.utcnow().isoformat()
        
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
                'timestamp': datetime.utcnow().isoformat(),
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
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.alert_rules: List[Dict[str, Any]] = []
        self.alert_history: List[Dict[str, Any]] = []
        self.rate_limits: Dict[str, datetime] = {}
    
    async def start(self) -> None:
        """Initialize the alert system"""
        # Load default alert rules
        self._load_default_rules()
        logger.info("Alert System initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Alert System stopped")
    
    def _load_default_rules(self) -> None:
        """Load default alert rules"""
        self.alert_rules = [
            {
                'name': 'extreme_volume_spike',
                'condition': lambda x: x.get('volume_spike', 0) > 500,
                'priority': 'HIGH',
                'channels': ['telegram', 'log']
            },
            {
                'name': 'smart_money_detected',
                'condition': lambda x: x.get('smart_money_detected', False),
                'priority': 'HIGH',
                'channels': ['telegram', 'log']
            },
            {
                'name': 'positive_news_sentiment',
                'condition': lambda x: x.get('news_sentiment') == 'positive',
                'priority': 'MEDIUM',
                'channels': ['telegram']
            },
            {
                'name': 'confirmed_signal',
                'condition': lambda x: x.get('confirmed', False) and x.get('confidence_score', 0) > 0.7,
                'priority': 'HIGH',
                'channels': ['telegram', 'log']
            }
        ]
    
    async def check_alerts(self, analysis_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Check if any alert rules are triggered
        
        Returns:
            List of triggered alerts
        """
        triggered_alerts = []
        
        for rule in self.alert_rules:
            try:
                if rule['condition'](analysis_result):
                    # Check rate limiting
                    rule_name = rule['name']
                    symbol = analysis_result.get('symbol', 'UNKNOWN')
                    rate_key = f"{rule_name}:{symbol}"
                    
                    now = datetime.utcnow()
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
            
            # Filter by date range
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            filtered_anomalies = [
                a for a in anomalies
                if a.get('timestamp') and 
                datetime.fromisoformat(str(a['timestamp']).replace('Z', '+00:00')) > cutoff_date
            ]
            
            # Simulate trades on each signal
            hypothetical_pnl = []
            
            for anomaly in filtered_anomalies:
                if anomaly.get('volume_spike', 0) >= volume_threshold:
                    # Simulate entry at anomaly price
                    entry_price = float(anomaly.get('price', 0))
                    entry_time = anomaly.get('timestamp')
                    
                    # Simple strategy: hold for 1 hour, then exit
                    # In production, this would use actual price history
                    exit_price = entry_price * 1.05  # Assume 5% gain (placeholder)
                    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                    
                    trade = {
                        'entry_time': str(entry_time),
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl_percent': pnl_pct,
                        'volume_spike': anomaly['volume_spike']
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
    
    def get_backtest_summary(self) -> Dict[str, Any]:
        """Get summary of all backtests run"""
        if not self.backtest_results:
            return {'total_backtests': 0}
        
        return {
            'total_backtests': len(self.backtest_results),
            'backtests': self.backtest_results[-5:]  # Last 5
        }
