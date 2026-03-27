import redis.asyncio as aioredis
from backend.config import settings
import logging

logger = logging.getLogger(__name__)

redis_pool = None

async def init_redis():
    global redis_pool
    redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
        max_connections=20,
    )

async def get_redis():
    global redis_pool
    if redis_pool is None:
        await init_redis()
    # Verify the connection is alive, reconnect if dead
    try:
        await redis_pool.ping()
    except Exception:
        logger.warning("Redis connection lost, reconnecting...")
        await init_redis()
    return redis_pool
