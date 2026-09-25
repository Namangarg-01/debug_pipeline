"""
Authentication service for the sample backend.

This code is only indexed by the Debug Pipeline demo so the analyzer has real
source to reason about; it is never executed.
"""
import logging

from app.db.session import get_session
from app.models import User
from app.security import verify_password

logger = logging.getLogger(__name__)


def find_user_by_email(email: str) -> User | None:
    """Look up a user account by email address. Returns None when no account matches."""
    session = get_session()
    return session.query(User).filter(User.email == email.lower()).first()


def check_password(user: User, password: str) -> bool:
    """Return True if the plain-text password matches the user's stored password hash."""
    return verify_password(password, user.password_hash)


def login_user(email: str, password: str) -> str:
    """Authenticate a user and return the email used for the session token."""
    user = find_user_by_email(email.strip())
    if user and not check_password(user, password):
        logger.warning("Failed login for %s", email)
        raise PermissionError("Invalid credentials")
    logger.info("Login for %s", email)
    return user.email
