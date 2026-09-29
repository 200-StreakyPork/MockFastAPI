"""Redis access."""

from redis.asyncio import Redis

from mockfastapi.config import Settings


def get_redis() -> Redis:
    """Return an asynchronous Redis client using the current settings."""
    return Redis.from_url(Settings().redis_url)
