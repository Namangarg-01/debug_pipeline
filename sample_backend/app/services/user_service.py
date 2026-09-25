"""
User profile service for the sample backend.

This code is only indexed by the Debug Pipeline demo so the analyzer has real
source to reason about; it is never executed.
"""
from app.cache.redis_cache import get_cached_profile, set_cached_profile
from app.db.session import get_session
from app.models import User


def get_profile(user_id: int) -> dict:
    """Return a user's profile, reading from the Redis cache first and the database on a miss."""
    cached = get_cached_profile(user_id)
    if cached:
        return cached

    session = get_session()
    user = session.get(User, user_id)
    profile = {"id": user.id, "email": user.email, "name": user.full_name}
    set_cached_profile(user_id, profile)
    return profile


def update_display_name(user_id: int, name: str) -> None:
    """Change a user's display name."""
    session = get_session()
    user = session.get(User, user_id)
    user.full_name = name.strip()
    session.commit()
