"""
Redis 客户端连接
"""

import json
from typing import Optional, Any
from redis.asyncio import Redis, ConnectionPool

from ..config import settings


# 连接池
redis_pool: Optional[ConnectionPool] = None
redis_client: Optional[Redis] = None


async def init_redis():
    """初始化 Redis 连接"""
    global redis_pool, redis_client
    redis_pool = ConnectionPool(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        max_connections=20,
        decode_responses=True,
    )
    redis_client = Redis(connection_pool=redis_pool)


async def close_redis():
    """关闭 Redis 连接"""
    if redis_client:
        await redis_client.close()
    if redis_pool:
        await redis_pool.disconnect()


async def get_redis() -> Redis:
    """获取 Redis 客户端（依赖注入）"""
    if redis_client is None:
        await init_redis()
    return redis_client


# ---- 便捷方法 ----
class RedisHelper:
    """Redis 辅助操作类"""

    @staticmethod
    async def set_json(key: str, data: dict, expire: int = 3600):
        """存储 JSON 数据"""
        client = await get_redis()
        await client.setex(key, expire, json.dumps(data, ensure_ascii=False))

    @staticmethod
    async def get_json(key: str) -> Optional[dict]:
        """读取 JSON 数据"""
        client = await get_redis()
        value = await client.get(key)
        return json.loads(value) if value else None

    @staticmethod
    async def cache_session(session_id: str, data: dict, expire: int = 1800):
        """缓存面试会话"""
        await RedisHelper.set_json(f"session:{session_id}", data, expire)

    @staticmethod
    async def get_session(session_id: str) -> Optional[dict]:
        """获取缓存的会话"""
        return await RedisHelper.get_json(f"session:{session_id}")

    @staticmethod
    async def delete_session(session_id: str):
        """删除会话缓存"""
        client = await get_redis()
        await client.delete(f"session:{session_id}")
