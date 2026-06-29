"""
AI & Machine Learning Module for Crypto Oracle AI
Pattern Recognition, Sentiment Analysis, Social Volume Tracking
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import deque

import numpy as np
import pandas as pd
import httpx
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class PatternRecognizer:
    """
    Recognizes pump/dump patterns using ML-inspired techniques
    Implements pattern matching for common crypto manipulation schemes
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # Pattern templates (simplified feature vectors)
        self.pattern_templates = {
            'classic_pump': {
                'volume_spike_min': 300,
                'price_increase_rate': 0.5,  # 50% in short time
                'duration_minutes': 30,
                'followed_by_dump': True
            },
            'slow_accumulation': {
                'volume_spike_min': 50,
                'price_increase_rate': 0.15,
                'duration_minutes': 120,
                'followed_by_dump': False
            },
            'whale_manipulation': {
                'volume_spike_min': 200,
                'price_increase_rate': 0.3,
                'duration_minutes': 15,
                'large_transactions': True
            },
            'coordinated_pump': {
                'volume_spike_min': 500,
                'price_increase_rate': 0.8,
                'duration_minutes': 10,
                'social_mentions_spike': True
            }
        }
        
        # Historical data buffer for pattern matching
        self.price_history: Dict[str, deque] = {}
        self.volume_history: Dict[str, deque] = {}
        self.max_history_length = 1000
    
    async def start(self) -> None:
        """Initialize the pattern recognizer"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Pattern Recognizer initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Pattern Recognizer stopped")
    
    def update_price_data(self, symbol: str, price: float, volume: float) -> None:
        """Update price and volume history for a symbol"""
        timestamp = datetime.utcnow()
        
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.max_history_length)
            self.volume_history[symbol] = deque(maxlen=self.max_history_length)
        
        self.price_history[symbol].append((timestamp, price))
        self.volume_history[symbol].append((timestamp, volume))
    
    async def recognize_pattern(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze current price/volume action to identify patterns
        
        Returns:
            Pattern match results with confidence scores
        """
        result = {
            'symbol': symbol,
            'detected_patterns': [],
            'pattern_confidence': {},
            'current_phase': 'UNKNOWN',
            'recommendation': 'HOLD',
            'risk_level': 'MEDIUM'
        }
        
        try:
            if symbol not in self.price_history or len(self.price_history[symbol]) < 10:
                return result
            
            # Convert to DataFrame for analysis
            prices = [p for _, p in self.price_history[symbol]]
            volumes = [v for _, v in self.volume_history[symbol]]
            
            df = pd.DataFrame({
                'price': prices,
                'volume': volumes
            })
            
            # Calculate technical indicators
            df['price_change_pct'] = df['price'].pct_change() * 100
            df['volume_change_pct'] = df['volume'].pct_change() * 100
            df['rsi'] = self._calculate_rsi(df['price'], period=14)
            df['ma_20'] = df['price'].rolling(window=20).mean()
            
            # Get latest values
            latest = df.iloc[-1]
            
            # Check each pattern template
            for pattern_name, template in self.pattern_templates.items():
                confidence = self._match_pattern(df, template)
                
                if confidence > 0.6:  # 60% match threshold
                    result['detected_patterns'].append(pattern_name)
                    result['pattern_confidence'][pattern_name] = confidence
            
            # Determine current phase
            recent_price_change = df['price_change_pct'].tail(10).mean()
            recent_volume_change = df['volume_change_pct'].tail(10).mean()
            
            if recent_price_change > 20 and recent_volume_change > 200:
                result['current_phase'] = 'PUMP_IN_PROGRESS'
                result['recommendation'] = 'AVOID_FOMO'
                result['risk_level'] = 'HIGH'
            elif recent_price_change < -15 and recent_volume_change > 100:
                result['current_phase'] = 'DUMP_IN_PROGRESS'
                result['recommendation'] = 'CUT_LOSSES'
                result['risk_level'] = 'HIGH'
            elif recent_price_change > 5 and recent_volume_change > 50:
                result['current_phase'] = 'ACCUMULATION'
                result['recommendation'] = 'WATCH'
                result['risk_level'] = 'MEDIUM'
            else:
                result['current_phase'] = 'NORMAL'
                result['recommendation'] = 'HOLD'
                result['risk_level'] = 'LOW'
            
        except Exception as e:
            logger.error(f"Error recognizing pattern for {symbol}: {e}")
        
        return result
    
    def _match_pattern(self, df: pd.DataFrame, template: Dict[str, Any]) -> float:
        """
        Match current data against a pattern template
        Returns confidence score (0-1)
        """
        confidence = 0.0
        factors_checked = 0
        
        # Check volume spike
        recent_volume = df['volume'].tail(5).mean()
        avg_volume = df['volume'].tail(50).mean()
        
        if avg_volume > 0:
            volume_spike = ((recent_volume - avg_volume) / avg_volume) * 100
            if volume_spike >= template['volume_spike_min']:
                confidence += 0.3
            factors_checked += 1
        
        # Check price increase rate
        recent_price_change = df['price'].pct_change(periods=10).tail(1).iloc[0]
        if not np.isnan(recent_price_change):
            if recent_price_change >= template['price_increase_rate']:
                confidence += 0.3
            factors_checked += 1
        
        # Check duration (simplified)
        if len(df) >= template['duration_minutes'] // 5:  # Assuming 5-min candles
            confidence += 0.2
            factors_checked += 1
        
        # Normalize confidence
        if factors_checked > 0:
            confidence = min(confidence, 1.0)
        
        return confidence
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


class SentimentAnalyzer:
    """
    Advanced NLP-based sentiment analysis for crypto news and social media
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # Enhanced sentiment keywords with weights
        self.sentiment_lexicon = {
            'positive': {
                'moon': 0.8, 'pump': 0.7, 'surge': 0.7, 'rally': 0.7,
                'breakout': 0.6, 'bullish': 0.6, 'buy': 0.5, 'upgrade': 0.6,
                'partnership': 0.7, 'adoption': 0.7, 'listing': 0.6,
                'milestone': 0.5, 'record': 0.5, 'growth': 0.5,
                'innovation': 0.5, 'success': 0.5, 'profit': 0.6
            },
            'negative': {
                'dump': 0.8, 'crash': 0.8, 'sell': 0.7, 'bearish': 0.6,
                'hack': 0.9, 'scam': 0.9, 'exploit': 0.9, 'lawsuit': 0.7,
                'ban': 0.8, 'warning': 0.6, 'investigation': 0.7,
                'loss': 0.6, 'decline': 0.5, 'drop': 0.5, 'fall': 0.5,
                'risk': 0.4, 'concern': 0.4, 'fear': 0.5
            },
            'neutral': {
                'update': 0.1, 'announcement': 0.1, 'news': 0.1,
                'report': 0.1, 'analysis': 0.1, 'review': 0.1
            }
        }
    
    async def start(self) -> None:
        """Initialize the sentiment analyzer"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Sentiment Analyzer initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Sentiment Analyzer stopped")
    
    async def analyze_sentiment(self, symbol: str, text_sources: List[str]) -> Dict[str, Any]:
        """
        Analyze sentiment from multiple text sources
        
        Args:
            symbol: Token symbol
            text_sources: List of text content (news, tweets, etc.)
        
        Returns:
            Sentiment analysis results
        """
        result = {
            'symbol': symbol,
            'overall_sentiment': 'neutral',
            'sentiment_score': 0.0,  # -1 to +1
            'positive_score': 0.0,
            'negative_score': 0.0,
            'neutral_score': 0.0,
            'confidence': 0.0,
            'key_phrases': [],
            'sources_analyzed': 0
        }
        
        try:
            total_positive = 0.0
            total_negative = 0.0
            total_neutral = 0.0
            key_phrases = []
            
            for text in text_sources:
                if not text:
                    continue
                
                text_lower = text.lower()
                sources_analyzed = result['sources_analyzed'] + 1
                
                # Score positive keywords
                for word, weight in self.sentiment_lexicon['positive'].items():
                    if word in text_lower:
                        total_positive += weight
                        key_phrases.append(f"+{word}")
                
                # Score negative keywords
                for word, weight in self.sentiment_lexicon['negative'].items():
                    if word in text_lower:
                        total_negative += weight
                        key_phrases.append(f"-{word}")
                
                # Score neutral keywords
                for word, weight in self.sentiment_lexicon['neutral'].items():
                    if word in text_lower:
                        total_neutral += weight
            
            result['sources_analyzed'] = sources_analyzed
            
            # Calculate normalized scores
            total_score = total_positive + total_negative + total_neutral
            
            if total_score > 0:
                result['positive_score'] = total_positive / total_score
                result['negative_score'] = total_negative / total_score
                result['neutral_score'] = total_neutral / total_score
                
                # Overall sentiment score (-1 to +1)
                result['sentiment_score'] = (total_positive - total_negative) / total_score
                
                # Determine overall sentiment
                if result['sentiment_score'] > 0.3:
                    result['overall_sentiment'] = 'positive'
                elif result['sentiment_score'] < -0.3:
                    result['overall_sentiment'] = 'negative'
                else:
                    result['overall_sentiment'] = 'neutral'
                
                # Confidence based on amount of data
                result['confidence'] = min(1.0, sources_analyzed / 10)
            
            result['key_phrases'] = list(set(key_phrases))[:10]  # Top 10 unique phrases
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment for {symbol}: {e}")
        
        return result
    
    async def analyze_social_volume(self, symbol: str) -> Dict[str, Any]:
        """
        Track social media mention volume for a symbol
        
        Returns:
            Social volume metrics and trends
        """
        result = {
            'symbol': symbol,
            'mention_count_24h': 0,
            'mention_change_pct': 0.0,
            'trending': False,
            'platforms': {
                'twitter': 0,
                'reddit': 0,
                'telegram': 0,
                'discord': 0
            },
            'sentiment_breakdown': {}
        }
        
        try:
            # This would integrate with social media APIs
            # For now, return placeholder structure
            logger.debug(f"Analyzing social volume for {symbol}")
            
        except Exception as e:
            logger.error(f"Error analyzing social volume for {symbol}: {e}")
        
        return result


class WhaleTracker:
    """
    Tracks large wallet movements and whale activity patterns
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # Whale threshold (in USD)
        self.whale_threshold = 100000  # $100k+ transactions
        
        # Known whale wallets
        self.whale_wallets: set = set()
    
    async def start(self) -> None:
        """Initialize the whale tracker"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        await self._load_known_whales()
        logger.info("Whale Tracker initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Whale Tracker stopped")
    
    async def _load_known_whales(self) -> None:
        """Load known whale wallets from database"""
        try:
            smart_wallets = await self.db.get_smart_wallets()
            self.whale_wallets.update([w['address'] for w in smart_wallets])
        except Exception as e:
            logger.error(f"Error loading known whales: {e}")
    
    async def track_large_transactions(self, token_address: str) -> Dict[str, Any]:
        """
        Monitor for large transactions in a token
        
        Returns:
            Large transaction alerts and whale activity summary
        """
        result = {
            'token_address': token_address,
            'large_transactions': [],
            'whale_activity_detected': False,
            'net_whale_flow': 0.0,
            'unique_whales_active': 0
        }
        
        try:
            if not self.settings.etherscan_api_key:
                return result
            
            # Get recent token transfers
            params = {
                'module': 'account',
                'action': 'tokentx',
                'contractaddress': token_address,
                'startblock': 0,
                'endblock': 99999999,
                'sort': 'desc',
                'apikey': self.settings.etherscan_api_key
            }
            
            response = await self.http_client.get(
                self.settings.etherscan_base_url,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == '1' and data.get('result'):
                    transactions = data['result'][:50]  # Last 50 transactions
                    
                    whale_txs = []
                    active_whales = set()
                    net_flow = 0.0
                    
                    for tx in transactions:
                        value_usd = self._estimate_value_usd(
                            tx.get('value', '0'),
                            tx.get('tokenSymbol', '')
                        )
                        
                        if value_usd >= self.whale_threshold:
                            whale_txs.append({
                                'hash': tx.get('hash'),
                                'from': tx.get('from'),
                                'to': tx.get('to'),
                                'value_usd': value_usd,
                                'timestamp': tx.get('timeStamp'),
                                'is_whale_wallet': (
                                    tx.get('from') in self.whale_wallets or 
                                    tx.get('to') in self.whale_wallets
                                )
                            })
                            
                            # Track active whales
                            if tx.get('from') in self.whale_wallets:
                                active_whales.add(tx.get('from'))
                                net_flow -= value_usd
                            if tx.get('to') in self.whale_wallets:
                                active_whales.add(tx.get('to'))
                                net_flow += value_usd
                    
                    result['large_transactions'] = whale_txs[:10]  # Top 10
                    result['whale_activity_detected'] = len(whale_txs) > 0
                    result['net_whale_flow'] = net_flow
                    result['unique_whales_active'] = len(active_whales)
                    
        except Exception as e:
            logger.error(f"Error tracking large transactions: {e}")
        
        return result
    
    def _estimate_value_usd(self, value: str, symbol: str) -> float:
        """Estimate USD value of a token amount (simplified)"""
        try:
            # This would need real-time price data
            # Simplified placeholder
            value_float = float(value) / (10 ** 18)  # Assume 18 decimals
            
            # Rough estimates for common tokens
            price_estimates = {
                'USDT': 1.0,
                'USDC': 1.0,
                'ETH': 2000,
                'BTC': 30000,
                'BNB': 300
            }
            
            price = price_estimates.get(symbol.upper(), 1.0)
            return value_float * price
            
        except (ValueError, TypeError):
            return 0.0
