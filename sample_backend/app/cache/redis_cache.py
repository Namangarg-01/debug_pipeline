"""
Redis cache helpers for the sample backend.

This code is only indexed by the Debug Pipeline demo so the analyzer has real
source to reason about; it is never executed.
"""
import json

import redis

client = redis.Redis(host="redis", port=6379, socket_connect_timeout=2)


def get_cached_profile(user_id: int) -> dict | None:
    """Return the cached profile for a user from Redis, or None on a cache miss."""
    raw = client.get(f"profile:{user_id}")
    return json.loads(raw) if raw else None


def set_cached_profile(user_id: int, profile: dict, ttl_seconds: int = 300) -> None:
    """Store a user's profile in Redis for ttl_seconds."""
    client.setex(f"profile:{user_id}", ttl_seconds, json.dumps(profile))
