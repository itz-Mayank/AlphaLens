from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip
from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.rate_limit import limiter
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.schemas.user import UserRead
from app.services.auth_service import AuthService, IssuedTokens

router = APIRouter()
settings = get_settings()


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.refresh_cookie_name, path="/api/v1/auth")


def _to_token_response(user: User, tokens: IssuedTokens) -> AccessTokenResponse:
    return AccessTokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.access_token_expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/register", response_model=AccessTokenResponse, status_code=201)
@limiter.limit("10/hour")
def register(
    request: Request,
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    service = AuthService(db)
    user, tokens = service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        user_agent=request.headers.get("user-agent"),
        ip_address=get_client_ip(request),
    )
    _set_refresh_cookie(response, tokens)
    return _to_token_response(user, tokens)


@router.post("/login", response_model=AccessTokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    service = AuthService(db)
    user, tokens = service.login(
        email=payload.email,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=get_client_ip(request),
    )
    _set_refresh_cookie(response, tokens)
    return _to_token_response(user, tokens)


@router.post("/refresh", response_model=AccessTokenResponse)
@limiter.limit("30/minute")
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    raw_refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_refresh_token:
        raise UnauthorizedError("No active session.", code="NO_REFRESH_TOKEN")

    service = AuthService(db)
    user, tokens = service.refresh(
        raw_refresh_token=raw_refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=get_client_ip(request),
    )
    _set_refresh_cookie(response, tokens)
    return _to_token_response(user, tokens)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    raw_refresh_token = request.cookies.get(settings.refresh_cookie_name)
    AuthService(db).logout(raw_refresh_token=raw_refresh_token, ip_address=get_client_ip(request))
    _clear_refresh_cookie(response)


@router.post("/forgot-password", status_code=204)
@limiter.limit("5/hour")
def forgot_password(
    request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)
) -> None:
    # Always returns 204 regardless of whether the email is registered, to
    # avoid leaking account existence.
    AuthService(db).forgot_password(email=payload.email, ip_address=get_client_ip(request))


@router.post("/reset-password", status_code=204)
@limiter.limit("10/hour")
def reset_password(
    request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)
) -> None:
    AuthService(db).reset_password(
        raw_token=payload.token,
        new_password=payload.new_password,
        ip_address=get_client_ip(request),
    )
