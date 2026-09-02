"""
Redis's job shrank once we looked closely at pycrdt-websocket: the Yjs
"awareness" protocol (cursors, presence, who's-online) is synchronized
in-memory by the room itself and broadcast to connected clients directly.
see the docstring in websocket/editor.py. At single-instance scale there's
nothing for Redis to do there.

JWT logout blocklist (so a "logged out" token can't still be used until it naturally expires) and a
simple brute-force guard on login. Both are real, small, and worth keeping.
"""
import redis.asyncio as redis

from .config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def revoke_token(token: str, ttl_seconds: int) -> None:
    """Blocklist a token until it would have expired naturally anyway
    no point keeping it around longer than that."""
    if ttl_seconds > 0:
        await get_redis().set(f"revoked:{token}", "1", ex=ttl_seconds)


async def is_token_revoked(token: str) -> bool:
    return bool(await get_redis().exists(f"revoked:{token}"))


async def check_and_record_login_attempt(
    identifier: str, max_attempts: int = 8, window_seconds: int = 300
) -> bool:
    """Fixed-window brute-force guard on /auth/login. Returns True if this
    attempt is allowed to proceed."""
    key = f"login_attempts:{identifier}"
    r = get_redis()
    attempts = await r.incr(key)
    if attempts == 1:
        await r.expire(key, window_seconds)
    return attempts <= max_attempts
