"""Request dependencies: database session, current user, CSRF, roles."""

from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.security import hash_token, tokens_match
from app.db import get_db
from app.models import User, UserSession

SESSION_COOKIE = "shop_session"
CSRF_COOKIE = "shop_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Avoid a write on every request: only bump last_seen_at when it's this stale.
_TOUCH_INTERVAL = timedelta(minutes=10)


def client_ip(request: Request) -> str | None:
    """The visitor's IP address, used for rate limits and the signature audit trail.

    X-Forwarded-For is never trusted: anyone can send it. In production a CloudFront
    Function overwrites X-Viewer-Ip with the address CloudFront actually saw, and the
    origin-secret check (main.py) guarantees the request came through CloudFront. Without
    an origin secret (local development) the socket address is used.
    """
    if get_settings().origin_secret.get_secret_value():
        viewer = request.headers.get("x-viewer-ip")
        if viewer:
            return viewer.strip()[:64]
    return request.client.host if request.client else None


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized("Please sign in.")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = datetime.now(UTC)
    settings = get_settings()
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.last_seen_at + timedelta(days=settings.session_idle_days) <= now
        or not session.user.is_active
    ):
        raise Unauthorized("Your session has ended. Please sign in again.")

    if request.method not in SAFE_METHODS:
        if not tokens_match(request.headers.get(CSRF_HEADER), session.csrf_token):
            raise Forbidden("Security check failed. Refresh the page and try again.", code="csrf")

    if now - session.last_seen_at > _TOUCH_INTERVAL:
        session.last_seen_at = now
    request.state.user = session.user
    return session


def require_user(session: UserSession = Depends(current_session)) -> User:
    return session.user


def require_role(*roles: str):
    def checker(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise Forbidden("You don't have access to this.")
        return user

    return checker
