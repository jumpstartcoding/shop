from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.deps import CSRF_COOKIE, SESSION_COOKIE, client_ip, current_session, require_user
from app.core.errors import AppError, TooManyRequests, Unauthorized
from app.core.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    verify_password,
)
from app.db import get_db
from app.models import User, UserSession
from app.schemas.auth import ChangePasswordIn, LoginIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_LOGIN = "That email and password don't match."


def _set_cookies(response: Response, token: str, csrf: str, max_age: int) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    # Readable by the SPA so it can echo it in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role)


@router.post("/login", response_model=SessionOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    now = datetime.now(UTC)
    user = db.scalar(
        select(User).where(func.lower(User.email) == data.email.lower()).with_for_update()
    )

    if user is not None and user.locked_until is not None and user.locked_until > now:
        raise TooManyRequests("Too many failed sign-in attempts. Wait a few minutes and try again.")

    ok = verify_password(user.password_hash if user else None, data.password)
    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_count = 0
            audit.record(
                db,
                user=None,
                actor="system",
                action="auth.login_failed",
                entity_type="user",
                entity_id=user.id,
                ip_address=client_ip(request),
            )
        # Commit the counter before the error unwinds the request transaction.
        db.commit()
        raise Unauthorized(_BAD_LOGIN)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    token, csrf = new_token(), new_token()
    max_age = settings.session_absolute_days * 86400
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_token=csrf,
            expires_at=now + timedelta(seconds=max_age),
            last_seen_at=now,
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    )
    audit.record(
        db,
        user=user,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        ip_address=client_ip(request),
    )
    _set_cookies(response, token, csrf, max_age)
    return SessionOut(user=_user_out(user), csrf_token=csrf)


@router.post("/logout", status_code=204)
def logout(response: Response, session: UserSession = Depends(current_session)):
    session.revoked_at = datetime.now(UTC)
    _clear_cookies(response)


@router.get("/me", response_model=SessionOut)
def me(session: UserSession = Depends(current_session)):
    return SessionOut(user=_user_out(session.user), csrf_token=session.csrf_token)


@router.post("/change-password", status_code=204)
def change_password(
    data: ChangePasswordIn,
    response: Response,
    request: Request,
    session: UserSession = Depends(current_session),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, data.current_password):
        raise AppError(
            "Your current password is incorrect.", status_code=400, code="wrong_password"
        )
    user.password_hash = hash_password(data.new_password)
    now = datetime.now(UTC)
    # Sign out every other device.
    for other in db.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.id != session.id,
            UserSession.revoked_at.is_(None),
        )
    ):
        other.revoked_at = now
    audit.record(
        db,
        user=user,
        action="auth.password_changed",
        entity_type="user",
        entity_id=user.id,
        ip_address=client_ip(request),
    )
