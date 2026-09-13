from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.schemas.providers import ProviderStatusListResponse, ProviderStatusRead
from app.services import provider_health_service

router = APIRouter()

# Provider health is operational/internal — same ANALYST/ADMIN restriction
# as model-lifecycle data (app/api/v1/models.py). Never exposes a
# credential value, only whether one is configured.
_OPS_ROLES = (UserRole.ANALYST, UserRole.ADMIN)


@router.get("/providers", response_model=ProviderStatusListResponse)
def get_provider_statuses(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(*_OPS_ROLES)),
) -> ProviderStatusListResponse:
    statuses = provider_health_service.get_provider_statuses(db)
    return ProviderStatusListResponse(
        providers=[ProviderStatusRead(**vars(s)) for s in statuses]
    )
