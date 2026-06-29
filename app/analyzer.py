"""
Deep Dive Analyzer for Crypto Oracle AI
Analyzes anomalies using Etherscan and CryptoPanic APIs
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import httpx
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class DeepDiveAnalyzer:
    """
    Analyzes detected anomalies using multiple data sources:
    - Etherscan: Check for smart wallet transactions
    - CryptoPanic: Check news sentiment
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        self.smart_wallets: List[str] = []
    
    async def _load_smart_wallets(self) -> List[str]:
        """Load smart wallet addresses from database"""
        try:
            wallets = await self.db.get_smart_wallets()
            return [w['address'] for w in wallets]
        except Exception as e:
            logger.error(f"Error loading smart wallets: {e}")
            return []
    
    async def start(self) -> None:
        """Initialize the analyzer"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.smart_wallets = await self._load_smart_wallets()
        logger.info("Deep Dive Analyzer initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Deep Dive Analyzer stopped")
    
    async def analyze_anomaly(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform deep analysis on a detected anomaly
        
        Args:
            anomaly_data: Dictionary containing symbol, price, volume_spike, etc.
        
        Returns:
            Analysis result with confirmation status and reasons
        """
        symbol = anomaly_data.get('symbol', '')
        
        logger.info(f"Starting deep analysis for {symbol}")
        
        # Initialize analysis result
        analysis_result = {
            'symbol': symbol,
            'confirmed': False,
            'reasons': [],
            'smart_money_detected': False,
            'news_sentiment': 'neutral',
            'confidence_score': 0.0,
            'details': {}
        }
        
        # Run all checks concurrently
        tasks = []
        
        # Check Etherscan for smart wallet activity
        if self.settings.etherscan_api_key:
            tasks.append(self._check_etherscan(symbol))
        else:
            logger.warning("Etherscan API key not configured")
        
        # Check CryptoPanic for news sentiment
        if self.settings.cryptopanic_api_key:
            tasks.append(self._check_cryptopanic(symbol))
        else:
            logger.warning("CryptoPanic API key not configured")
        
        # Execute all checks
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process Etherscan result
            etherscan_result = None
            cryptopanic_result = None
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Analysis task failed: {result}")
                elif isinstance(result, dict):
                    if 'type' in result:
                        if result['type'] == 'etherscan':
                            etherscan_result = result
                        elif result['type'] == 'cryptopanic':
                            cryptopanic_result = result
            
            # Process Etherscan findings
            if etherscan_result and etherscan_result.get('smart_money_found'):
                analysis_result['smart_money_detected'] = True
                analysis_result['reasons'].append('Smart Money terdeteksi beli')
                analysis_result['confidence_score'] += 0.4
                analysis_result['details']['etherscan'] = etherscan_result
            
            # Process CryptoPanic findings
            if cryptopanic_result:
                sentiment = cryptopanic_result.get('sentiment', 'neutral')
                analysis_result['news_sentiment'] = sentiment
                analysis_result['details']['cryptopanic'] = cryptopanic_result
                
                if sentiment == 'positive':
                    analysis_result['reasons'].append('Sentimen berita positif')
                    analysis_result['confidence_score'] += 0.3
                elif sentiment == 'bullish':
                    analysis_result['reasons'].append('Sentimen berita bullish')
                    analysis_result['confidence_score'] += 0.35
        
        # Add volume spike reason
        volume_spike = anomaly_data.get('volume_spike', 0)
        if volume_spike >= self.settings.volume_spike_threshold:
            analysis_result['reasons'].append(f'Volume naik {volume_spike:.0f}%')
            analysis_result['confidence_score'] += 0.3
        
        # Determine if signal is confirmed
        # Confirmed if: volume spike + (smart money OR positive news)
        if (analysis_result['smart_money_detected'] or 
            analysis_result['news_sentiment'] in ['positive', 'bullish']):
            analysis_result['confirmed'] = True
        
        logger.info(
            f"Analysis complete for {symbol}: "
            f"Confirmed={analysis_result['confirmed']}, "
            f"Confidence={analysis_result['confidence_score']:.2f}"
        )
        
        return analysis_result
    
    async def _check_etherscan(self, symbol: str) -> Dict[str, Any]:
        """
        Check Etherscan for smart wallet transactions related to the symbol
        
        Note: This is a simplified implementation. In production, you would need
        to map symbol addresses and check specific token contracts.
        """
        result = {
            'type': 'etherscan',
            'symbol': symbol,
            'smart_money_found': False,
            'transactions': [],
            'checked_wallets': 0
        }
        
        try:
            # For demonstration, we'll check recent ETH transfers
            # In production, you'd need to map tokens to their contract addresses
            
            # Get token contract address (simplified mapping)
            token_address = await self._get_token_address(symbol)
            
            if not token_address:
                # Try checking ETH directly for wrapped tokens
                logger.debug(f"No contract address found for {symbol}")
                return result
            
            # Check transactions for each smart wallet
            for wallet in self.smart_wallets[:10]:  # Limit to first 10 wallets
                try:
                    params = {
                        'module': 'account',
                        'action': 'tokentx',
                        'contractaddress': token_address,
                        'address': wallet,
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
                            transactions = data['result'][:5]  # Last 5 transactions
                            
                            # Check for recent buys (last 10 minutes)
                            current_time = datetime.utcnow().timestamp()
                            ten_minutes_ago = current_time - (10 * 60)
                            
                            for tx in transactions:
                                tx_time = int(tx.get('timeStamp', 0))
                                if tx_time > ten_minutes_ago:
                                    # Check if it's a buy transaction
                                    if self._is_buy_transaction(tx, wallet):
                                        result['smart_money_found'] = True
                                        result['transactions'].append({
                                            'wallet': wallet,
                                            'tx_hash': tx.get('hash'),
                                            'value': tx.get('value'),
                                            'timestamp': tx_time
                                        })
                            
                            result['checked_wallets'] += 1
                            
                except Exception as e:
                    logger.error(f"Error checking wallet {wallet}: {e}")
                    continue
            
            if result['smart_money_found']:
                logger.info(f"Smart money detected for {symbol}")
            
        except Exception as e:
            logger.error(f"Etherscan check failed for {symbol}: {e}")
        
        return result
    
    async def _check_cryptopanic(self, symbol: str) -> Dict[str, Any]:
        """
        Check CryptoPanic for news sentiment about the symbol
        """
        result = {
            'type': 'cryptopanic',
            'symbol': symbol,
            'sentiment': 'neutral',
            'news_count': 0,
            'articles': []
        }
        
        try:
            # Extract base symbol (remove USDT suffix)
            base_symbol = symbol.replace('USDT', '')
            
            params = {
                'auth_token': self.settings.cryptopanic_api_key,
                'currencies': base_symbol,
                'kind': 'news',
                'limit': 10
            }
            
            response = await self.http_client.get(
                f"{self.settings.cryptopanic_base_url}/posts/",
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                articles = data.get('results', [])
                
                result['news_count'] = len(articles)
                
                # Analyze sentiment from recent articles
                if articles:
                    positive_count = 0
                    negative_count = 0
                    
                    for article in articles[:5]:  # Analyze last 5 articles
                        title = article.get('title', '').lower()
                        body = article.get('body', '').lower()
                        
                        # Simple keyword-based sentiment analysis
                        positive_keywords = [
                            'pump', 'moon', 'surge', 'rally', 'breakout',
                            'bullish', 'buy', 'upgrade', 'partnership', 'adoption'
                        ]
                        negative_keywords = [
                            'dump', 'crash', 'sell', 'bearish', 'hack',
                            'scam', 'exploit', 'lawsuit', 'ban', 'warning'
                        ]
                        
                        text = f"{title} {body}"
                        
                        for keyword in positive_keywords:
                            if keyword in text:
                                positive_count += 1
                        
                        for keyword in negative_keywords:
                            if keyword in text:
                                negative_count += 1
                    
                    # Determine overall sentiment
                    if positive_count > negative_count:
                        result['sentiment'] = 'positive'
                    elif negative_count > positive_count:
                        result['sentiment'] = 'negative'
                    else:
                        result['sentiment'] = 'neutral'
                    
                    result['articles'] = [
                        {
                            'title': article.get('title'),
                            'url': article.get('url'),
                            'published_at': article.get('published_at')
                        }
                        for article in articles[:3]
                    ]
                    
                    logger.info(
                        f"CryptoPanic analysis for {symbol}: "
                        f"Sentiment={result['sentiment']}, Articles={result['news_count']}"
                    )
            
        except Exception as e:
            logger.error(f"CryptoPanic check failed for {symbol}: {e}")
        
        return result
    
    async def _get_token_address(self, symbol: str) -> Optional[str]:
        """
        Get token contract address for a symbol
        This is a simplified mapping - in production, use a proper token database
        """
        # Common token addresses on Ethereum
        token_mapping = {
            'ETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # WETH
            'BTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',  # WBTC
            'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
            'BNB': '0xB8c77482e45F1F44dE1745F52C74426C631bDD52',
            'XRP': '0x1d2F0da169ceB9fC7B3144628dB156f3F6c60dBE',
            'ADA': '0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47',
            'DOGE': '0xba2ae424d960c26247dd6c32edc70b295c744c43',
            'SOL': '0xD31a59c85aE9D8edEFeC411D448f90841571b89c',
            'DOT': '0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402',
            'MATIC': '0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0',
            'LINK': '0x514910771AF9Ca656af840dff83E8264EcF986CA',
            'UNI': '0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984',
            'AAVE': '0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9',
        }
        
        base_symbol = symbol.replace('USDT', '')
        return token_mapping.get(base_symbol)
    
    def _is_buy_transaction(self, tx: Dict[str, Any], wallet: str) -> bool:
        """
        Determine if a transaction is a buy transaction
        Simplified logic - in production, use DEX router analysis
        """
        # Check if wallet is the recipient (potential buy)
        if tx.get('to', '').lower() == wallet.lower():
            return True
        
        # Additional logic could be added here to analyze DEX interactions
        return False
