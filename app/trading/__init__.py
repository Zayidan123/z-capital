"""
Trading Module for Crypto Oracle AI
Auto-Snipe, Dynamic TP/SL, Portfolio Tracking
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


@dataclass
class TradePosition:
    """Represents an active trading position"""
    symbol: str
    entry_price: float
    entry_time: datetime
    amount: float
    stop_loss: float
    take_profit_levels: List[float]
    current_price: float = 0.0
    pnl_percent: float = 0.0
    status: str = 'ACTIVE'  # ACTIVE, CLOSED, STOPPED_OUT


class RiskManager:
    """
    Manages trading risk with dynamic stop-loss and take-profit
    Implements position sizing and risk/reward calculations
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.active_positions: Dict[str, TradePosition] = {}
        
        # Risk parameters
        self.max_position_size_pct = 0.02  # 2% of portfolio per trade
        self.default_stop_loss_pct = 0.10  # 10% stop loss
        self.take_profit_levels_pct = [0.20, 0.40, 0.60]  # 20%, 40%, 60%
        self.max_daily_loss_pct = 0.05  # 5% max daily loss
    
    async def start(self) -> None:
        """Initialize the risk manager"""
        logger.info("Risk Manager initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Risk Manager stopped")
    
    def calculate_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_loss_price: float
    ) -> float:
        """
        Calculate optimal position size based on risk parameters
        
        Args:
            portfolio_value: Total portfolio value in USD
            entry_price: Entry price per token
            stop_loss_price: Stop loss price per token
        
        Returns:
            Number of tokens to buy
        """
        # Risk amount (2% of portfolio)
        risk_amount = portfolio_value * self.max_position_size_pct
        
        # Risk per token
        risk_per_token = entry_price - stop_loss_price
        
        if risk_per_token <= 0:
            logger.warning("Invalid stop loss: must be below entry price")
            return 0.0
        
        # Position size in tokens
        position_size = risk_amount / risk_per_token
        
        return position_size
    
    def calculate_dynamic_stop_loss(
        self,
        entry_price: float,
        volatility: float,
        atr: Optional[float] = None
    ) -> float:
        """
        Calculate dynamic stop loss based on volatility
        
        Args:
            entry_price: Entry price
            volatility: Price volatility (percentage)
            atr: Average True Range (optional)
        
        Returns:
            Stop loss price
        """
        # Use ATR-based stop loss if available
        if atr and atr > 0:
            stop_distance = atr * 2  # 2x ATR
        else:
            # Use volatility-based stop loss
            stop_distance = entry_price * (volatility / 100) * 1.5
        
        stop_loss = entry_price - stop_distance
        
        # Ensure minimum stop loss distance
        min_stop = entry_price * (1 - self.default_stop_loss_pct)
        stop_loss = max(stop_loss, min_stop)
        
        return round(stop_loss, 8)
    
    def calculate_take_profit_levels(
        self,
        entry_price: float,
        levels: Optional[List[float]] = None
    ) -> List[float]:
        """
        Calculate multiple take profit levels
        
        Args:
            entry_price: Entry price
            levels: Profit percentages (default: [20%, 40%, 60%])
        
        Returns:
            List of take profit prices
        """
        if levels is None:
            levels = self.take_profit_levels_pct
        
        tp_prices = []
        for level in levels:
            tp_price = entry_price * (1 + level)
            tp_prices.append(round(tp_price, 8))
        
        return tp_prices
    
    async def open_position(
        self,
        symbol: str,
        entry_price: float,
        portfolio_value: float,
        volatility: float = 10.0
    ) -> Optional[TradePosition]:
        """
        Open a new trading position with proper risk management
        
        Returns:
            TradePosition object or None if invalid
        """
        try:
            # Calculate stop loss
            stop_loss = self.calculate_dynamic_stop_loss(entry_price, volatility)
            
            # Calculate position size
            position_size = self.calculate_position_size(
                portfolio_value, entry_price, stop_loss
            )
            
            if position_size <= 0:
                logger.warning(f"Invalid position size for {symbol}")
                return None
            
            # Calculate take profit levels
            tp_levels = self.calculate_take_profit_levels(entry_price)
            
            # Create position
            position = TradePosition(
                symbol=symbol,
                entry_price=entry_price,
                entry_time=datetime.utcnow(),
                amount=position_size,
                stop_loss=stop_loss,
                take_profit_levels=tp_levels,
                current_price=entry_price
            )
            
            # Store position
            self.active_positions[symbol] = position
            
            logger.info(
                f"Opened position: {symbol} | "
                f"Entry: ${entry_price:.8f} | "
                f"Size: {position_size:.4f} | "
                f"SL: ${stop_loss:.8f} | "
                f"TP: {[f'${tp:.8f}' for tp in tp_levels]}"
            )
            
            return position
            
        except Exception as e:
            logger.error(f"Error opening position for {symbol}: {e}")
            return None
    
    async def update_position(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Update position with current price and check for exits
        
        Returns:
            Action taken: None, 'STOPPED_OUT', 'TP_HIT', or 'UPDATE'
        """
        if symbol not in self.active_positions:
            return None
        
        position = self.active_positions[symbol]
        position.current_price = current_price
        
        # Calculate PnL
        pnl_percent = (current_price - position.entry_price) / position.entry_price
        position.pnl_percent = pnl_percent
        
        # Check stop loss
        if current_price <= position.stop_loss:
            position.status = 'STOPPED_OUT'
            logger.warning(
                f"🛑 STOP LOSS HIT: {symbol} | "
                f"Entry: ${position.entry_price:.8f} | "
                f"Exit: ${current_price:.8f} | "
                f"PnL: {pnl_percent*100:.2f}%"
            )
            return 'STOPPED_OUT'
        
        # Check take profit levels
        for i, tp in enumerate(position.take_profit_levels):
            if current_price >= tp and position.status == 'ACTIVE':
                # Partial take profit logic could be implemented here
                logger.info(
                    f"✅ TAKE PROFIT LEVEL {i+1} HIT: {symbol} | "
                    f"Price: ${current_price:.8f} | "
                    f"PnL: {pnl_percent*100:.2f}%"
                )
                # Remove hit TP level
                position.take_profit_levels.pop(i)
                return 'TP_HIT'
        
        return 'UPDATE'
    
    def get_position_summary(self) -> Dict[str, Any]:
        """Get summary of all active positions"""
        summary = {
            'total_positions': len(self.active_positions),
            'active_positions': [],
            'total_pnl_percent': 0.0,
            'positions_in_profit': 0,
            'positions_in_loss': 0
        }
        
        total_pnl = 0.0
        
        for symbol, position in self.active_positions.items():
            pos_data = asdict(position)
            summary['active_positions'].append(pos_data)
            
            total_pnl += position.pnl_percent
            
            if position.pnl_percent > 0:
                summary['positions_in_profit'] += 1
            elif position.pnl_percent < 0:
                summary['positions_in_loss'] += 1
        
        if summary['total_positions'] > 0:
            summary['total_pnl_percent'] = total_pnl / summary['total_positions']
        
        return summary


class AutoSniper:
    """
    Automated sniping module for quick entries on confirmed signals
    """
    
    def __init__(self, db: Database, risk_manager: RiskManager):
        self.settings = get_settings()
        self.db = db
        self.risk_manager = risk_manager
        self.http_client = None
        self.enabled = False
        self.portfolio_value = 10000  # Default $10k portfolio
    
    async def start(self) -> None:
        """Initialize the auto sniper"""
        logger.info("Auto Sniper initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Auto Sniper stopped")
    
    def enable(self) -> None:
        """Enable auto sniping"""
        self.enabled = True
        logger.warning("⚠️ AUTO SNIPING ENABLED - Use at your own risk!")
    
    def disable(self) -> None:
        """Disable auto sniping"""
        self.enabled = False
        logger.info("Auto sniping disabled")
    
    async def execute_snipe(
        self,
        symbol: str,
        current_price: float,
        confidence_score: float,
        volatility: float = 10.0
    ) -> Optional[TradePosition]:
        """
        Execute a snipe trade on a confirmed signal
        
        Args:
            symbol: Token symbol
            current_price: Current market price
            confidence_score: Signal confidence (0-1)
            volatility: Token volatility percentage
        
        Returns:
            TradePosition if executed, None otherwise
        """
        if not self.enabled:
            logger.debug(f"Auto sniping disabled, skipping {symbol}")
            return None
        
        # Check confidence threshold
        if confidence_score < 0.6:
            logger.debug(f"Confidence too low for {symbol}: {confidence_score}")
            return None
        
        # Adjust position size based on confidence
        original_max_size = self.risk_manager.max_position_size_pct
        self.risk_manager.max_position_size_pct = original_max_size * confidence_score
        
        try:
            # Open position
            position = await self.risk_manager.open_position(
                symbol=symbol,
                entry_price=current_price,
                portfolio_value=self.portfolio_value,
                volatility=volatility
            )
            
            if position:
                logger.info(
                    f"🎯 SNIPE EXECUTED: {symbol} | "
                    f"Price: ${current_price:.8f} | "
                    f"Confidence: {confidence_score:.0%}"
                )
            
            return position
            
        finally:
            # Restore original position size
            self.risk_manager.max_position_size_pct = original_max_size
    
    async def cancel_snipe(self, symbol: str) -> bool:
        """Cancel a pending snipe order"""
        if symbol in self.risk_manager.active_positions:
            del self.risk_manager.active_positions[symbol]
            logger.info(f"Cancelled snipe for {symbol}")
            return True
        return False


class PortfolioTracker:
    """
    Tracks portfolio performance across all trades
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.initial_balance = 10000  # Starting balance
        self.current_balance = self.initial_balance
        self.trade_history: List[Dict[str, Any]] = []
    
    async def start(self) -> None:
        """Initialize the portfolio tracker"""
        logger.info("Portfolio Tracker initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        logger.info("Portfolio Tracker stopped")
    
    def record_trade(
        self,
        symbol: str,
        action: str,  # BUY or SELL
        price: float,
        amount: float,
        pnl: float = 0.0
    ) -> None:
        """Record a trade in history"""
        trade = {
            'timestamp': datetime.utcnow().isoformat(),
            'symbol': symbol,
            'action': action,
            'price': price,
            'amount': amount,
            'value': price * amount,
            'pnl': pnl
        }
        
        self.trade_history.append(trade)
        
        if action == 'SELL':
            self.current_balance += pnl
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Calculate portfolio performance metrics"""
        if not self.trade_history:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'roi_percent': 0.0
            }
        
        winning_trades = [t for t in self.trade_history if t['pnl'] > 0]
        losing_trades = [t for t in self.trade_history if t['pnl'] < 0]
        
        total_pnl = sum(t['pnl'] for t in self.trade_history)
        roi_percent = ((self.current_balance - self.initial_balance) / self.initial_balance) * 100
        
        return {
            'total_trades': len(self.trade_history),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trade_history) if self.trade_history else 0,
            'total_pnl': total_pnl,
            'current_balance': self.current_balance,
            'initial_balance': self.initial_balance,
            'roi_percent': roi_percent
        }
