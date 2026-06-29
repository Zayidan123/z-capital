"""
Multi-Chain Module for Crypto Oracle AI
Multi-chain support and CEX-DEX arbitrage scanning
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

import httpx
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class MultiChainMonitor:
    """
    Monitors multiple blockchain networks for cross-chain opportunities
    Supports: Ethereum, BSC, Polygon, Arbitrum, Optimism
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # Supported chains with RPC endpoints (public/free tier)
        self.chains = {
            'ETH': {
                'name': 'Ethereum',
                'chain_id': 1,
                'explorer': 'https://etherscan.io',
                'explorer_api': 'https://api.etherscan.io/api'
            },
            'BSC': {
                'name': 'Binance Smart Chain',
                'chain_id': 56,
                'explorer': 'https://bscscan.com',
                'explorer_api': 'https://api.bscscan.com/api'
            },
            'POLYGON': {
                'name': 'Polygon',
                'chain_id': 137,
                'explorer': 'https://polygonscan.com',
                'explorer_api': 'https://api.polygonscan.com/api'
            },
            'ARBITRUM': {
                'name': 'Arbitrum One',
                'chain_id': 42161,
                'explorer': 'https://arbiscan.io',
                'explorer_api': 'https://api.arbiscan.io/api'
            },
            'OPTIMISM': {
                'name': 'Optimism',
                'chain_id': 10,
                'explorer': 'https://optimistic.etherscan.io',
                'explorer_api': 'https://api-optimistic.etherscan.io/api'
            }
        }
        
        # API keys per chain (would need separate keys for each)
        self.chain_api_keys = {
            'ETH': self.settings.etherscan_api_key,
            'BSC': None,  # Would need BSCScan API key
            'POLYGON': None,  # Would need PolygonScan API key
            'ARBITRUM': None,
            'OPTIMISM': None
        }
    
    async def start(self) -> None:
        """Initialize the multi-chain monitor"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"Multi-Chain Monitor initialized for {len(self.chains)} chains")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Multi-Chain Monitor stopped")
    
    async def get_token_price_multi_chain(
        self,
        token_address: str,
        chains: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get token price across multiple chains
        
        Returns:
            Price data per chain
        """
        if chains is None:
            chains = list(self.chains.keys())
        
        result = {
            'token_address': token_address,
            'prices_by_chain': {},
            'price_differences': [],
            'arbitrage_opportunities': []
        }
        
        tasks = [
            self._get_token_price_on_chain(token_address, chain)
            for chain in chains
        ]
        
        prices = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_prices = {}
        for i, chain in enumerate(chains):
            if isinstance(prices[i], dict) and prices[i].get('price_usd', 0) > 0:
                valid_prices[chain] = prices[i]
                result['prices_by_chain'][chain] = prices[i]
        
        # Calculate price differences
        if len(valid_prices) >= 2:
            chains_list = list(valid_prices.keys())
            
            for i in range(len(chains_list)):
                for j in range(i + 1, len(chains_list)):
                    chain1 = chains_list[i]
                    chain2 = chains_list[j]
                    
                    price1 = valid_prices[chain1]['price_usd']
                    price2 = valid_prices[chain2]['price_usd']
                    
                    diff_pct = abs(price1 - price2) / min(price1, price2) * 100
                    
                    result['price_differences'].append({
                        'chain1': chain1,
                        'chain2': chain2,
                        'price1': price1,
                        'price2': price2,
                        'difference_pct': diff_pct
                    })
                    
                    # Flag arbitrage opportunity if difference > 2%
                    if diff_pct > 2.0:
                        result['arbitrage_opportunities'].append({
                            'buy_chain': chain1 if price1 < price2 else chain2,
                            'sell_chain': chain2 if price1 < price2 else chain1,
                            'buy_price': min(price1, price2),
                            'sell_price': max(price1, price2),
                            'profit_pct': diff_pct
                        })
        
        return result
    
    async def _get_token_price_on_chain(
        self,
        token_address: str,
        chain: str
    ) -> Dict[str, Any]:
        """Get token price on a specific chain"""
        result = {
            'chain': chain,
            'token_address': token_address,
            'price_usd': 0.0,
            'price_native': 0.0,
            'liquidity_usd': 0.0,
            'volume_24h': 0.0
        }
        
        try:
            api_key = self.chain_api_keys.get(chain)
            chain_info = self.chains.get(chain)
            
            if not api_key or not chain_info:
                return result
            
            # Get token info from explorer API
            params = {
                'module': 'token',
                'action': 'tokeninfo',
                'contractaddress': token_address,
                'apikey': api_key
            }
            
            response = await self.http_client.get(
                chain_info['explorer_api'],
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == '1' and data.get('result'):
                    token_info = data['result'][0] if isinstance(data['result'], list) else data['result']
                    
                    # Extract price data if available
                    result['price_native'] = float(token_info.get('tokenPrice', '0'))
                    # Would need native token price to convert to USD
                    
        except Exception as e:
            logger.debug(f"Could not fetch price for {token_address} on {chain}: {e}")
        
        return result
    
    async def scan_new_tokens(self, chain: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Scan for newly deployed tokens on a chain
        
        Returns:
            List of new token contracts
        """
        new_tokens = []
        
        try:
            api_key = self.chain_api_keys.get(chain)
            chain_info = self.chains.get(chain)
            
            if not api_key or not chain_info:
                return new_tokens
            
            # This would use a dedicated new token API or monitor contract creation events
            # Simplified placeholder
            logger.debug(f"Scanning for new tokens on {chain}")
            
        except Exception as e:
            logger.error(f"Error scanning new tokens on {chain}: {e}")
        
        return new_tokens


class ArbitrageScanner:
    """
    Scans for arbitrage opportunities between CEX and DEX
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # CEX APIs
        self.cex_exchanges = ['binance', 'coinbase', 'kraken', 'okx']
        
        # DEX routers per chain
        self.dex_routers = {
            'ETH': {
                'uniswap_v2': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
                'uniswap_v3': '0xE592427A0AEce92De3Edee1F18E0157C05861564',
                'sushiswap': '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F'
            },
            'BSC': {
                'pancakeswap_v2': '0x10ED43C718714eb63d5aA57B78B54704E256024E',
                'pancakeswap_v3': '0x13f4EA83D0bd40E75C8222255bc855a974568Dd4'
            }
        }
        
        # Minimum profit threshold after fees
        self.min_profit_pct = 1.0  # 1% minimum
        self.estimated_gas_fee_usd = 50  # Average gas fee
    
    async def start(self) -> None:
        """Initialize the arbitrage scanner"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Arbitrage Scanner initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Arbitrage Scanner stopped")
    
    async def scan_cex_dex_arbitrage(
        self,
        symbol: str
    ) -> Dict[str, Any]:
        """
        Scan for price differences between CEX and DEX
        
        Returns:
            Arbitrage opportunities if found
        """
        result = {
            'symbol': symbol,
            'opportunities': [],
            'cex_prices': {},
            'dex_prices': {},
            'best_opportunity': None
        }
        
        try:
            # Get CEX prices
            cex_tasks = [
                self._get_cex_price(symbol, exchange)
                for exchange in self.cex_exchanges
            ]
            cex_results = await asyncio.gather(*cex_tasks, return_exceptions=True)
            
            for i, exchange in enumerate(self.cex_exchanges):
                if isinstance(cex_results[i], dict) and cex_results[i].get('price', 0) > 0:
                    result['cex_prices'][exchange] = cex_results[i]
            
            # Get DEX prices (simplified - would need actual DEX queries)
            dex_tasks = [
                self._get_dex_price(symbol, chain)
                for chain in ['ETH', 'BSC']
            ]
            dex_results = await asyncio.gather(*dex_tasks, return_exceptions=True)
            
            for i, chain in enumerate(['ETH', 'BSC']):
                if isinstance(dex_results[i], dict) and dex_results[i].get('price', 0) > 0:
                    result['dex_prices'][chain] = dex_results[i]
            
            # Find arbitrage opportunities
            all_prices = {**result['cex_prices'], **result['dex_prices']}
            
            if len(all_prices) >= 2:
                sources = list(all_prices.keys())
                
                for i in range(len(sources)):
                    for j in range(i + 1, len(sources)):
                        source1 = sources[i]
                        source2 = sources[j]
                        
                        price1 = all_prices[source1]['price']
                        price2 = all_prices[source2]['price']
                        
                        # Calculate potential profit
                        diff_pct = abs(price1 - price2) / min(price1, price2) * 100
                        
                        # Account for fees
                        net_profit_pct = diff_pct - self.estimated_gas_fee_usd / min(price1, price2) * 100
                        
                        if net_profit_pct >= self.min_profit_pct:
                            opportunity = {
                                'buy_source': source1 if price1 < price2 else source2,
                                'sell_source': source2 if price1 < price2 else source1,
                                'buy_price': min(price1, price2),
                                'sell_price': max(price1, price2),
                                'gross_profit_pct': diff_pct,
                                'net_profit_pct': net_profit_pct,
                                'estimated_gas_fee': self.estimated_gas_fee_usd
                            }
                            
                            result['opportunities'].append(opportunity)
                
                # Sort by profit
                if result['opportunities']:
                    result['opportunities'].sort(
                        key=lambda x: x['net_profit_pct'],
                        reverse=True
                    )
                    result['best_opportunity'] = result['opportunities'][0]
                    
        except Exception as e:
            logger.error(f"Error scanning arbitrage for {symbol}: {e}")
        
        return result
    
    async def _get_cex_price(
        self,
        symbol: str,
        exchange: str
    ) -> Dict[str, Any]:
        """Get price from a CEX"""
        result = {
            'exchange': exchange,
            'symbol': symbol,
            'price': 0.0,
            'volume_24h': 0.0
        }
        
        try:
            if exchange == 'binance':
                url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
                response = await self.http_client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    result['price'] = float(data.get('price', 0))
            
            elif exchange == 'coinbase':
                url = f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot"
                response = await self.http_client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    result['price'] = float(data.get('data', {}).get('amount', 0))
            
            # Add more exchanges as needed
            
        except Exception as e:
            logger.debug(f"Could not fetch price from {exchange}: {e}")
        
        return result
    
    async def _get_dex_price(
        self,
        symbol: str,
        chain: str
    ) -> Dict[str, Any]:
        """Get price from a DEX (simplified)"""
        result = {
            'chain': chain,
            'symbol': symbol,
            'price': 0.0,
            'dex': 'unknown'
        }
        
        # In production, this would query actual DEX contracts or subgraphs
        # For now, return placeholder
        
        return result
