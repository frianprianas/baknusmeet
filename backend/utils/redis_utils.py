import redis.asyncio as redis
from backend.config import settings

redis_pool = None

async def init_redis():
    global redis_pool
    # Modern redis-py (redis.asyncio) uses the same from_url signature
    redis_pool = await redis.from_url(settings.REDIS_URL, decode_responses=True)

async def get_redis():
    if redis_pool is None:
        await init_redis()
    return redis_pool
