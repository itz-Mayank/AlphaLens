from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_client_ip, get_current_user
from app.db.models.audit_log import AuditAction
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.auth import ChangePasswordRequest, DeleteAccountRequest
from app.schemas.user import UserRead, UserUpdate
from app.services.auth_service import AuthService

router = APIRouter()


@router.get("/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
def update_me(
    request: Request,
    payload: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRead:
    user.full_name = payload.full_name
    AuditLogRepository(db).record(
        action=AuditAction.PROFILE_UPDATED, user_id=user.id, ip_address=get_client_ip(request)
    )
    db.flush()
    return UserRead.model_validate(user)


@router.post("/me/change-password", status_code=204)
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    AuthService(db).change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ip_address=get_client_ip(request),
    )


@router.delete("/me", status_code=204)
def delete_me(
    request: Request,
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    AuthService(db).delete_account(
        user=user, password=payload.password, ip_address=get_client_ip(request)
    )
