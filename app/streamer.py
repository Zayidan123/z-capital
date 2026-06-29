"""
Real-Time Streamer for Crypto Oracle AI
Monitors Binance WebSocket for volume anomalies
"""
import asyncio
import logging
import json
import time
from typing import Dict, List, Optional, Callable, Any
from collections import defaultdict
from datetime import datetime, timedelta

import websockets
import pandas as pd
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class VolumeTracker:
    """Tracks volume data for symbols in a rolling window"""
    
    def __init__(self, window_minutes: int = 5):
        self.window_minutes = window_minutes
        self.window_seconds = window_minutes * 60
        # Store volume data: {symbol: [(timestamp, volume), ...]}
        self.volume_data: Dict[str, List[tuple]] = defaultdict(list)
        # Store current ticker data
        self.current_tickers: Dict[str, Dict[str, Any]] = {}
    
    def update_ticker(self, symbol: str, data: Dict[str, Any]) -> None:
        """Update ticker data for a symbol"""
        self.current_tickers[symbol] = data
        
        # Extract volume (24h volume in quote asset)
        volume = float(data.get('q', 0))  # 'q' is quote volume in USDT
        timestamp = time.time()
        
        # Add to volume history
        self.volume_data[symbol].append((timestamp, volume))
        
        # Clean old data outside the window
        cutoff = timestamp - self.window_seconds
        self.volume_data[symbol] = [
            (ts, vol) for ts, vol in self.volume_data[symbol]
            if ts > cutoff
        ]
    
    def calculate_volume_spike(self, symbol: str) -> Optional[float]:
        """
        Calculate volume spike percentage for a symbol
        Returns the spike percentage or None if insufficient data
        """
        if symbol not in self.volume_data or len(self.volume_data[symbol]) < 2:
            return None
        
        volumes = [vol for _, vol in self.volume_data[symbol]]
        
        if len(volumes) < 2:
            return None
        
        # Calculate average volume in the window
        avg_volume = sum(volumes) / len(volumes)
        
        # Current volume (most recent)
        current_volume = volumes[-1]
        
        if avg_volume == 0:
            return None
        
        # Calculate spike percentage
        spike = ((current_volume - avg_volume) / avg_volume) * 100
        
        return spike
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        if symbol in self.current_tickers:
            return float(self.current_tickers[symbol].get('c', 0))
        return None
    
    def get_volume_stats(self, symbol: str) -> Dict[str, Any]:
        """Get volume statistics for a symbol"""
        if symbol not in self.volume_data or len(self.volume_data[symbol]) == 0:
            return {}
        
        volumes = [vol for _, vol in self.volume_data[symbol]]
        
        return {
            'current_volume': volumes[-1] if volumes else 0,
            'avg_volume': sum(volumes) / len(volumes) if volumes else 0,
            'min_volume': min(volumes) if volumes else 0,
            'max_volume': max(volumes) if volumes else 0,
            'data_points': len(volumes)
        }


class BinanceStreamer:
    """
    Real-time streamer for Binance WebSocket
    Monitors all USDT pairs for volume anomalies
    """
    
    def __init__(
        self,
        db: Database,
        anomaly_callback: Optional[Callable] = None
    ):
        self.settings = get_settings()
        self.db = db
        self.anomaly_callback = anomaly_callback
        self.volume_tracker = VolumeTracker(
            window_minutes=self.settings.volume_window_minutes
        )
        self.running = False
        self.ws_url = self.settings.binance_ws_url
        self.websocket = None
        self.reconnect_delay = 5
        self.processed_symbols = set()  # Track symbols we've already alerted on
        self.cooldown_period = 300  # 5 minutes cooldown per symbol
    
    async def start(self) -> None:
        """Start the Binance WebSocket streamer"""
        self.running = True
        logger.info(f"Starting Binance streamer: {self.ws_url}")
        
        while self.running:
            try:
                await self._connect_and_stream()
            except Exception as e:
                logger.error(f"Streamer error: {e}")
                if self.running:
                    logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
    
    async def stop(self) -> None:
        """Stop the streamer"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
        logger.info("Binance streamer stopped")
    
    async def _connect_and_stream(self) -> None:
        """Connect to WebSocket and process messages"""
        try:
            async with websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                self.websocket = websocket
                logger.info("Connected to Binance WebSocket")
                
                while self.running:
                    try:
                        message = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=60
                        )
                        await self._process_message(message)
                    except asyncio.TimeoutError:
                        # Send ping to keep connection alive
                        pong = await websocket.ping()
                        await asyncio.wait_for(pong, timeout=10)
                    except Exception as e:
                        logger.error(f"Message processing error: {e}")
                        break
                        
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            raise
    
    async def _process_message(self, message: str) -> None:
        """Process incoming WebSocket message"""
        try:
            data = json.loads(message)
            
            # Handle different message formats
            if 'stream' in data:
                # Stream format: {"stream": "<streamName>", "data": {...}}
                payload = data.get('data', {})
            else:
                # Direct data format
                payload = data
            
            # Handle ticker data
            if isinstance(payload, list):
                # Multiple tickers in one message
                for ticker in payload:
                    await self._process_ticker(ticker)
            elif isinstance(payload, dict):
                # Single ticker
                await self._process_ticker(payload)
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def _process_ticker(self, ticker: Dict[str, Any]) -> None:
        """Process individual ticker data"""
        try:
            # Extract symbol (remove 'USDT' suffix for cleaner display)
            symbol = ticker.get('s', '')
            
            # Only process USDT pairs
            if not symbol.endswith('USDT'):
                return
            
            # Update volume tracker
            self.volume_tracker.update_ticker(symbol, ticker)
            
            # Check for volume anomaly
            spike = self.volume_tracker.calculate_volume_spike(symbol)
            
            if spike is not None and spike >= self.settings.volume_spike_threshold:
                # Check cooldown period
                if self._is_in_cooldown(symbol):
                    return
                
                # Get current price
                price = self.volume_tracker.get_current_price(symbol)
                
                # Get volume stats
                volume_stats = self.volume_tracker.get_volume_stats(symbol)
                
                logger.warning(
                    f"🚨 VOLUME ANOMALY DETECTED: {symbol} | "
                    f"Spike: {spike:.2f}% | "
                    f"Price: ${price:.8f} | "
                    f"Volume: {volume_stats['current_volume']:.2f} USDT"
                )
                
                # Log to database
                await self.db.log_anomaly(
                    symbol=symbol,
                    price=price if price else 0,
                    volume_spike=spike,
                    volume_current=volume_stats['current_volume'],
                    volume_avg=volume_stats['avg_volume']
                )
                
                # Mark symbol as processed (start cooldown)
                self._add_to_cooldown(symbol)
                
                # Call anomaly callback if provided
                if self.anomaly_callback:
                    anomaly_data = {
                        'symbol': symbol,
                        'price': price,
                        'volume_spike': spike,
                        'volume_current': volume_stats['current_volume'],
                        'volume_avg': volume_stats['avg_volume'],
                        'timestamp': datetime.utcnow().isoformat()
                    }
                    await self.anomaly_callback(anomaly_data)
                    
        except Exception as e:
            logger.error(f"Error processing ticker {ticker.get('s', 'UNKNOWN')}: {e}")
    
    def _is_in_cooldown(self, symbol: str) -> bool:
        """Check if symbol is in cooldown period"""
        if symbol in self.processed_symbols:
            return True
        return False
    
    def _add_to_cooldown(self, symbol: str) -> None:
        """Add symbol to cooldown tracking"""
        self.processed_symbols.add(symbol)
        
        # Schedule removal from cooldown after cooldown period
        asyncio.create_task(self._remove_from_cooldown(symbol))
    
    async def _remove_from_cooldown(self, symbol: str) -> None:
        """Remove symbol from cooldown after cooldown period"""
        await asyncio.sleep(self.cooldown_period)
        self.processed_symbols.discard(symbol)
        logger.debug(f"Removed {symbol} from cooldown")
