"""
Security Module for Crypto Oracle AI
Honeypot Detector, Liquidity Lock Checker, Holder Distribution Analysis
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import httpx
from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class HoneypotDetector:
    """
    Detects potential honeypot tokens by analyzing:
    - Buy/sell tax rates
    - Liquidity lock status
    - Contract verification
    - Holder distribution
    - Trading restrictions
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        # Known honeypot patterns
        self.honeypot_indicators = {
            'high_sell_tax': 0.3,  # Sell tax > 30%
            'low_liquidity': 10000,  # Liquidity < $10k
            'concentrated_holdings': 0.5,  # Top 10 holders > 50%
            'unverified_contract': True,
            'trading_cooldown': 300,  # Cooldown > 5 minutes
        }
    
    async def start(self) -> None:
        """Initialize the honeypot detector"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Honeypot Detector initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Honeypot Detector stopped")
    
    async def check_token_safety(self, token_address: str, symbol: str) -> Dict[str, Any]:
        """
        Perform comprehensive safety check on a token
        
        Args:
            token_address: Contract address of the token
            symbol: Token symbol
        
        Returns:
            Safety analysis result with risk score and indicators
        """
        logger.info(f"Checking token safety for {symbol} ({token_address})")
        
        result = {
            'symbol': symbol,
            'token_address': token_address,
            'is_safe': True,
            'risk_score': 0.0,  # 0-100, higher is riskier
            'honeypot_probability': 0.0,
            'indicators': {},
            'warnings': [],
            'recommendation': 'SAFE'
        }
        
        try:
            # Run all checks concurrently
            tasks = [
                self._check_trading_tax(token_address),
                self._check_liquidity_lock(token_address),
                self._check_holder_distribution(token_address),
                self._check_contract_verification(token_address),
                self._check_trading_restrictions(token_address),
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process trading tax
            if isinstance(results[0], dict):
                result['indicators']['trading_tax'] = results[0]
                if results[0].get('sell_tax', 0) > self.honeypot_indicators['high_sell_tax'] * 100:
                    result['warnings'].append(f"High sell tax: {results[0].get('sell_tax', 0):.1f}%")
                    result['risk_score'] += 25
            
            # Process liquidity lock
            if isinstance(results[1], dict):
                result['indicators']['liquidity'] = results[1]
                if not results[1].get('is_locked', False):
                    result['warnings'].append("Liquidity is NOT locked")
                    result['risk_score'] += 20
                elif results[1].get('liquidity_usd', 0) < self.honeypot_indicators['low_liquidity']:
                    result['warnings'].append(f"Low liquidity: ${results[1].get('liquidity_usd', 0):.2f}")
                    result['risk_score'] += 15
            
            # Process holder distribution
            if isinstance(results[2], dict):
                result['indicators']['holder_distribution'] = results[2]
                top_10_percent = results[2].get('top_10_holders_percent', 0)
                if top_10_percent > self.honeypot_indicators['concentrated_holdings'] * 100:
                    result['warnings'].append(f"Concentrated holdings: Top 10 hold {top_10_percent:.1f}%")
                    result['risk_score'] += 20
            
            # Process contract verification
            if isinstance(results[3], dict):
                result['indicators']['contract_verified'] = results[3]
                if not results[3].get('is_verified', False):
                    result['warnings'].append("Contract is NOT verified")
                    result['risk_score'] += 15
            
            # Process trading restrictions
            if isinstance(results[4], dict):
                result['indicators']['trading_restrictions'] = results[4]
                if results[4].get('has_cooldown', False):
                    cooldown = results[4].get('cooldown_seconds', 0)
                    if cooldown > self.honeypot_indicators['trading_cooldown']:
                        result['warnings'].append(f"Trading cooldown: {cooldown}s")
                        result['risk_score'] += 10
            
            # Calculate honeypot probability
            result['honeypot_probability'] = min(result['risk_score'] / 100, 1.0)
            
            # Determine overall safety
            if result['risk_score'] >= 70:
                result['is_safe'] = False
                result['recommendation'] = 'HIGH_RISK'
            elif result['risk_score'] >= 40:
                result['is_safe'] = False
                result['recommendation'] = 'MEDIUM_RISK'
            elif result['risk_score'] >= 20:
                result['recommendation'] = 'LOW_RISK'
            else:
                result['recommendation'] = 'SAFE'
            
            logger.info(
                f"Safety check complete for {symbol}: "
                f"Risk Score={result['risk_score']}, "
                f"Recommendation={result['recommendation']}"
            )
            
        except Exception as e:
            logger.error(f"Error checking token safety for {symbol}: {e}")
            result['warnings'].append(f"Analysis failed: {str(e)}")
            result['risk_score'] = 50  # Default to medium risk on error
        
        return result
    
    async def _check_trading_tax(self, token_address: str) -> Dict[str, Any]:
        """Check buy/sell tax rates"""
        result = {
            'buy_tax': 0.0,
            'sell_tax': 0.0,
            'is_modifiable': False,
            'max_tax': 0.0
        }
        
        try:
            # Use GoPlus Security API (free tier available)
            url = f"https://api.goplussecurity.com/1/public/api/token_security/1/{token_address}"
            
            response = await self.http_client.get(url)
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == 1 and data.get('result'):
                    token_data = data['result'].get(token_address.lower(), {})
                    
                    buy_tax = token_data.get('buy_tax', '0')
                    sell_tax = token_data.get('sell_tax', '0')
                    
                    # Parse percentage values
                    try:
                        result['buy_tax'] = float(buy_tax) * 100 if buy_tax else 0
                        result['sell_tax'] = float(sell_tax) * 100 if sell_tax else 0
                        result['max_tax'] = max(result['buy_tax'], result['sell_tax'])
                    except (ValueError, TypeError):
                        pass
                    
                    # Check if tax is modifiable (red flag)
                    result['is_modifiable'] = token_data.get('is_honeypot_with_modify', '0') == '1'
                    
        except Exception as e:
            logger.debug(f"Could not fetch trading tax: {e}")
        
        return result
    
    async def _check_liquidity_lock(self, token_address: str) -> Dict[str, Any]:
        """Check if liquidity is locked and for how long"""
        result = {
            'is_locked': False,
            'liquidity_usd': 0.0,
            'locked_percentage': 0.0,
            'unlock_date': None,
            'lock_platform': None
        }
        
        try:
            # Use GoPlus Security API
            url = f"https://api.goplussecurity.com/1/public/api/token_security/1/{token_address}"
            
            response = await self.http_client.get(url)
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == 1 and data.get('result'):
                    token_data = data['result'].get(token_address.lower(), {})
                    
                    # Check liquidity info
                    lp_holder_count = token_data.get('lp_holder_count', '0')
                    try:
                        result['liquidity_usd'] = float(token_data.get('total_liquidity', '0'))
                    except (ValueError, TypeError):
                        pass
                    
                    # Check if LP tokens are locked
                    # This is simplified - in production, use dedicated LP lock APIs
                    if int(lp_holder_count) <= 2:
                        result['is_locked'] = True
                        result['locked_percentage'] = 100.0
                    
        except Exception as e:
            logger.debug(f"Could not fetch liquidity lock info: {e}")
        
        return result
    
    async def _check_holder_distribution(self, token_address: str) -> Dict[str, Any]:
        """Analyze holder distribution for concentration risk"""
        result = {
            'total_holders': 0,
            'top_10_holders_percent': 0.0,
            'top_50_holders_percent': 0.0,
            'creator_balance_percent': 0.0,
            'is_concentrated': False
        }
        
        try:
            # Use GoPlus Security API
            url = f"https://api.goplussecurity.com/1/public/api/token_security/1/{token_address}"
            
            response = await self.http_client.get(url)
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == 1 and data.get('result'):
                    token_data = data['result'].get(token_address.lower(), {})
                    
                    # Get holder concentration
                    holder_10 = token_data.get('holder_10', '0')
                    try:
                        result['top_10_holders_percent'] = float(holder_10) * 100 if holder_10 else 0
                    except (ValueError, TypeError):
                        pass
                    
                    # Check creator balance
                    creator_balance = token_data.get('creator_balance', '0')
                    try:
                        result['creator_balance_percent'] = float(creator_balance) * 100 if creator_balance else 0
                    except (ValueError, TypeError):
                        pass
                    
                    result['is_concentrated'] = result['top_10_holders_percent'] > 50
                    
        except Exception as e:
            logger.debug(f"Could not fetch holder distribution: {e}")
        
        return result
    
    async def _check_contract_verification(self, token_address: str) -> Dict[str, Any]:
        """Check if contract source code is verified"""
        result = {
            'is_verified': False,
            'compiler_version': None,
            'optimization_enabled': False,
            'proxy_contract': False
        }
        
        try:
            if not self.settings.etherscan_api_key:
                return result
            
            params = {
                'module': 'contract',
                'action': 'getsourcecode',
                'address': token_address,
                'apikey': self.settings.etherscan_api_key
            }
            
            response = await self.http_client.get(
                self.settings.etherscan_base_url,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == '1' and data.get('result'):
                    contract_info = data['result'][0]
                    
                    # Check if source code exists
                    if contract_info.get('SourceCode'):
                        result['is_verified'] = True
                        result['compiler_version'] = contract_info.get('CompilerVersion')
                        result['optimization_enabled'] = contract_info.get('OptimizationUsed') == '1'
                        
                        # Check if it's a proxy contract
                        result['proxy_contract'] = contract_info.get('Proxy') == '1'
                        
        except Exception as e:
            logger.debug(f"Could not fetch contract verification: {e}")
        
        return result
    
    async def _check_trading_restrictions(self, token_address: str) -> Dict[str, Any]:
        """Check for trading restrictions like cooldowns or blacklists"""
        result = {
            'has_cooldown': False,
            'cooldown_seconds': 0,
            'has_blacklist': False,
            'has_whitelist': False,
            'can_be_paused': False,
            'is_mintable': False
        }
        
        try:
            # Use GoPlus Security API
            url = f"https://api.goplussecurity.com/1/public/api/token_security/1/{token_address}"
            
            response = await self.http_client.get(url)
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == 1 and data.get('result'):
                    token_data = data['result'].get(token_address.lower(), {})
                    
                    # Check various restrictions
                    result['has_blacklist'] = token_data.get('is_blacklisted', '0') == '1'
                    result['has_whitelist'] = token_data.get('is_whitelisted', '0') == '1'
                    result['can_be_paused'] = token_data.get('can_take_back_ownership', '0') == '1'
                    result['is_mintable'] = token_data.get('is_mintable', '0') == '1'
                    
                    # Check for anti-whale mechanisms
                    anti_whale = token_data.get('anti_whale_modifiable', '0')
                    if anti_whale == '1':
                        result['has_cooldown'] = True
                        result['cooldown_seconds'] = 60  # Estimate
                        
        except Exception as e:
            logger.debug(f"Could not fetch trading restrictions: {e}")
        
        return result


class LiquidityLockChecker:
    """
    Specialized checker for liquidity lock status across multiple platforms
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
        self.lock_platforms = [
            'uniswap', 'pancakeswap', 'sushiswap',
            'team_finance', 'unicrypt', 'pinklock'
        ]
    
    async def start(self) -> None:
        """Initialize the liquidity lock checker"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Liquidity Lock Checker initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Liquidity Lock Checker stopped")
    
    async def check_all_platforms(self, token_address: str) -> Dict[str, Any]:
        """Check liquidity lock status across all supported platforms"""
        result = {
            'token_address': token_address,
            'platforms_checked': [],
            'locked_on': [],
            'total_locked_liquidity': 0.0,
            'earliest_unlock': None,
            'longest_lock_period': None
        }
        
        # In production, implement actual API calls to each platform
        # For now, return placeholder structure
        logger.info(f"Checking liquidity lock for {token_address}")
        
        return result


class HolderDistributionAnalyzer:
    """
    Analyzes token holder distribution for whale detection and concentration risk
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.http_client: Optional[httpx.AsyncClient] = None
    
    async def start(self) -> None:
        """Initialize the analyzer"""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Holder Distribution Analyzer initialized")
    
    async def stop(self) -> None:
        """Cleanup resources"""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Holder Distribution Analyzer stopped")
    
    async def analyze_distribution(self, token_address: str) -> Dict[str, Any]:
        """
        Comprehensive holder distribution analysis
        
        Returns:
            Distribution metrics including Gini coefficient, whale count, etc.
        """
        result = {
            'token_address': token_address,
            'total_holders': 0,
            'gini_coefficient': 0.0,
            'whale_addresses': [],
            'retail_addresses': 0,
            'contract_holders': 0,
            'exchange_wallets': 0,
            'risk_level': 'LOW'
        }
        
        try:
            # Use Etherscan token holder API
            if self.settings.etherscan_api_key:
                params = {
                    'module': 'token',
                    'action': 'tokenholderlist',
                    'contractaddress': token_address,
                    'apikey': self.settings.etherscan_api_key
                }
                
                response = await self.http_client.get(
                    self.settings.etherscan_base_url,
                    params=params
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == '1':
                        holders = data.get('result', [])
                        result['total_holders'] = len(holders)
                        
                        # Analyze distribution
                        if holders:
                            balances = [float(h.get('Share', 0)) for h in holders[:100]]
                            
                            # Calculate Gini coefficient (simplified)
                            if len(balances) > 1:
                                sorted_balances = sorted(balances)
                                n = len(sorted_balances)
                                total = sum(sorted_balances)
                                
                                if total > 0:
                                    cumsum = 0
                                    weighted_sum = 0
                                    for i, bal in enumerate(sorted_balances):
                                        cumsum += bal
                                        weighted_sum += (i + 1) * bal
                                    
                                    gini = (2 * weighted_sum) / (n * total) - (n + 1) / n
                                    result['gini_coefficient'] = max(0, min(1, gini))
                            
                            # Identify whales (>1% supply)
                            for holder in holders[:50]:
                                share = float(holder.get('Share', 0))
                                if share > 0.01:  # > 1%
                                    result['whale_addresses'].append({
                                        'address': holder.get('Address'),
                                        'balance': holder.get('Balance'),
                                        'share': share
                                    })
                            
                            # Determine risk level
                            if result['gini_coefficient'] > 0.8:
                                result['risk_level'] = 'HIGH'
                            elif result['gini_coefficient'] > 0.6:
                                result['risk_level'] = 'MEDIUM'
                            else:
                                result['risk_level'] = 'LOW'
                                
        except Exception as e:
            logger.error(f"Error analyzing holder distribution: {e}")
        
        return result
