"""
Infrastructure Module for Crypto Oracle AI
Redis caching, rate limiting, and horizontal scaling support
"""
import asyncio
import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

from app.config import get_settings
from app.database import Database

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis caching layer for improved performance and data sharing
    between multiple instances (horizontal scaling)
    """
    
    def __init__(self, db: Database):
        self.settings = get_settings()
        self.db = db
        self.redis: Optional[Any] = None
        self.enabled = False
    
    async def start(self) -> None:
        """Initialize Redis connection"""
        try:
            if aioredis is None:
                logger.warning("Redis package not installed, caching disabled")
                return
            
            # Get Redis URL from environment or use default
            redis_url = getattr(self.settings, 'redis_url', 'redis://localhost:6379')
            
            self.redis = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            
            # Test connection
            await self.redis.ping()
            
            self.enabled = True
            logger.info("Redis cache initialized successfully")
            
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Caching disabled.")
            self.enabled = False
    
    async def stop(self) -> None:
        """Cleanup Redis connection"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis cache stopped")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not self.enabled or not self.redis:
            return None
        
        try:
            value = await self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 300
    ) -> bool:
        """Set value in cache with TTL"""
        if not self.enabled or not self.redis:
            return False
        
        try:
            await self.redis.setex(
                key,
                ttl_seconds,
                json.dumps(value)
            )
            return True
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.enabled or not self.redis:
            return False
        
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")
            return False
    
    async def get_or_set(
        self,
        key: str,
        default_func,
        ttl_seconds: int = 300
    ) -> Any:
        """Get from cache or compute and cache if missing"""
        cached = await self.get(key)
        
        if cached is not None:
            return cached
        
        # Compute value
        value = await default_func()
        
        # Cache it
        await self.set(key, value, ttl_seconds)
        
        return value
    
    async def publish(self, channel: str, message: Dict[str, Any]) -> bool:
        """Publish message to Redis pub/sub channel"""
        if not self.enabled or not self.redis:
            return False
        
        try:
            await self.redis.publish(channel, json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Redis PUBLISH error: {e}")
            return False
    
    async def subscribe(self, channel: str):
        """Subscribe to Redis pub/sub channel"""
        if not self.enabled or not self.redis:
            return None
        
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(channel)
            return pubsub
        except Exception as e:
            logger.error(f"Redis SUBSCRIBE error: {e}")
            return None


class RateLimiter:
    """
    Rate limiter using Redis for distributed rate limiting
    Falls back to in-memory limiting if Redis is unavailable
    """
    
    def __init__(self, redis_cache: Optional[RedisCache] = None):
        self.redis_cache = redis_cache
        self.memory_limits: Dict[str, List[datetime]] = {}
        self.default_limit = 100  # requests per window
        self.window_seconds = 60
    
    async def is_allowed(
        self,
        identifier: str,
        limit: Optional[int] = None,
        window: Optional[int] = None
    ) -> bool:
        """
        Check if request is allowed under rate limit
        
        Args:
            identifier: Unique identifier (e.g., API key, IP, user ID)
            limit: Max requests per window
            window: Time window in seconds
        
        Returns:
            True if allowed, False if rate limited
        """
        limit = limit or self.default_limit
        window = window or self.window_seconds
        
        if self.redis_cache and self.redis_cache.enabled:
            return await self._redis_rate_limit(identifier, limit, window)
        else:
            return self._memory_rate_limit(identifier, limit, window)
    
    async def _redis_rate_limit(
        self,
        identifier: str,
        limit: int,
        window: int
    ) -> bool:
        """Redis-based rate limiting using sliding window"""
        try:
            key = f"rate_limit:{identifier}"
            now = datetime.utcnow().timestamp()
            window_start = now - window
            
            # Use Redis sorted set for sliding window
            pipe = self.redis_cache.redis.pipeline()
            
            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count current requests
            pipe.zcard(key)
            
            # Add current request
            pipe.zadd(key, {str(now): now})
            
            # Set expiry
            pipe.expire(key, window + 1)
            
            results = await pipe.execute()
            current_count = results[1]
            
            return current_count < limit
            
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            return True  # Fail open
    
    def _memory_rate_limit(
        self,
        identifier: str,
        limit: int,
        window: int
    ) -> bool:
        """In-memory rate limiting (single instance only)"""
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=window)
        
        if identifier not in self.memory_limits:
            self.memory_limits[identifier] = []
        
        # Clean old entries
        self.memory_limits[identifier] = [
            ts for ts in self.memory_limits[identifier]
            if ts > window_start
        ]
        
        # Check limit
        if len(self.memory_limits[identifier]) >= limit:
            return False
        
        # Add current request
        self.memory_limits[identifier].append(now)
        
        return True


class HorizontalScaler:
    """
    Supports horizontal scaling with distributed coordination
    """
    
    def __init__(self, db: Database, redis_cache: Optional[RedisCache] = None):
        self.settings = get_settings()
        self.db = db
        self.redis_cache = redis_cache
        self.instance_id = f"instance_{id(self)}"
        self.heartbeat_interval = 30  # seconds
    
    async def start(self) -> None:
        """Start the scaler coordination"""
        logger.info(f"Horizontal Scaler started with instance ID: {self.instance_id}")
        
        # Start heartbeat task
        asyncio.create_task(self._heartbeat_loop())
    
    async def stop(self) -> None:
        """Stop the scaler coordination"""
        # Remove instance from active instances
        await self._unregister_instance()
        logger.info("Horizontal Scaler stopped")
    
    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats"""
        while True:
            try:
                await self._send_heartbeat()
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(self.heartbeat_interval)
    
    async def _send_heartbeat(self) -> None:
        """Send heartbeat to Redis"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return
        
        try:
            key = "crypto_oracle:active_instances"
            
            heartbeat_data = {
                'instance_id': self.instance_id,
                'timestamp': datetime.utcnow().isoformat(),
                'status': 'healthy'
            }
            
            # Add to active instances set
            await self.redis_cache.redis.hset(
                key,
                self.instance_id,
                json.dumps(heartbeat_data)
            )
            
        except Exception as e:
            logger.error(f"Heartbeat send error: {e}")
    
    async def _unregister_instance(self) -> None:
        """Remove instance from active instances"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return
        
        try:
            key = "crypto_oracle:active_instances"
            await self.redis_cache.redis.hdel(key, self.instance_id)
        except Exception as e:
            logger.error(f"Unregister error: {e}")
    
    async def get_active_instances(self) -> List[Dict[str, Any]]:
        """Get list of active instances"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return [{'instance_id': self.instance_id, 'status': 'standalone'}]
        
        try:
            key = "crypto_oracle:active_instances"
            instances_data = await self.redis_cache.redis.hgetall(key)
            
            instances = []
            for instance_id, data_str in instances_data.items():
                try:
                    data = json.loads(data_str)
                    
                    # Check if heartbeat is recent (within 2 minutes)
                    timestamp = datetime.fromisoformat(data['timestamp'])
                    if (datetime.utcnow() - timestamp).total_seconds() < 120:
                        instances.append(data)
                        
                except Exception:
                    continue
            
            return instances
            
        except Exception as e:
            logger.error(f"Get active instances error: {e}")
            return [{'instance_id': self.instance_id, 'status': 'error'}]
    
    async def distribute_work(
        self,
        symbols: List[str]
    ) -> List[str]:
        """
        Distribute symbols across instances for load balancing
        
        Returns:
            Subset of symbols this instance should process
        """
        instances = await self.get_active_instances()
        
        if len(instances) <= 1:
            # Single instance, process all
            return symbols
        
        # Find this instance's index
        instance_index = 0
        for i, inst in enumerate(instances):
            if inst['instance_id'] == self.instance_id:
                instance_index = i
                break
        
        # Distribute symbols evenly
        num_instances = len(instances)
        symbols_per_instance = len(symbols) // num_instances
        
        start_idx = instance_index * symbols_per_instance
        end_idx = start_idx + symbols_per_instance if instance_index < num_instances - 1 else len(symbols)
        
        return symbols[start_idx:end_idx]


class MessageQueue:
    """
    Simple message queue using Redis for inter-service communication
    """
    
    def __init__(self, redis_cache: Optional[RedisCache] = None):
        self.redis_cache = redis_cache
        self.queue_prefix = "crypto_oracle:queue:"
    
    async def enqueue(
        self,
        queue_name: str,
        message: Dict[str, Any],
        priority: int = 0
    ) -> bool:
        """Add message to queue"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return False
        
        try:
            key = f"{self.queue_prefix}{queue_name}"
            
            # Use Redis list as queue (LPUSH for enqueue)
            message_with_meta = {
                **message,
                'queued_at': datetime.utcnow().isoformat(),
                'priority': priority
            }
            
            await self.redis_cache.redis.lpush(key, json.dumps(message_with_meta))
            
            return True
            
        except Exception as e:
            logger.error(f"Enqueue error: {e}")
            return False
    
    async def dequeue(
        self,
        queue_name: str,
        timeout: float = 0
    ) -> Optional[Dict[str, Any]]:
        """Get message from queue"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return None
        
        try:
            key = f"{self.queue_prefix}{queue_name}"
            
            # Use BRPOPLPUSH for atomic dequeue or RPOPLPUSH for non-blocking
            if timeout > 0:
                result = await self.redis_cache.redis.brpoplpush(
                    key,
                    f"{key}:processing",
                    timeout=timeout
                )
            else:
                result = await self.redis_cache.redis.rpoplpush(
                    key,
                    f"{key}:processing"
                )
            
            if result:
                return json.loads(result)
            
            return None
            
        except Exception as e:
            logger.error(f"Dequeue error: {e}")
            return None
    
    async def complete(
        self,
        queue_name: str,
        message: Dict[str, Any]
    ) -> bool:
        """Mark message as completed (remove from processing)"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return False
        
        try:
            processing_key = f"{self.queue_prefix}{queue_name}:processing"
            
            # Remove from processing queue
            await self.redis_cache.redis.lrem(
                processing_key,
                1,
                json.dumps(message)
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Complete error: {e}")
            return False
    
    async def queue_size(self, queue_name: str) -> int:
        """Get current queue size"""
        if not self.redis_cache or not self.redis_cache.enabled:
            return 0
        
        try:
            key = f"{self.queue_prefix}{queue_name}"
            return await self.redis_cache.redis.llen(key)
        except Exception as e:
            logger.error(f"Queue size error: {e}")
            return 0
