import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import NotFoundError
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.security_repository import SecurityRepository
from app.repositories.watchlist_repository import WatchlistRepository
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistDetailResponse,
    WatchlistItemAdd,
    WatchlistItemRead,
    WatchlistListItem,
    WatchlistRead,
)
from app.services.watchlist_service import get_watchlist_detail, get_watchlist_for_user

router = APIRouter()


def _resolve_security_id_or_404(db: Session, ticker: str) -> int:
    security = SecurityRepository(db).get_by_ticker(ticker)
    if security is None:
        raise NotFoundError(
            f"No stock found for ticker '{ticker.upper()}'.", code="STOCK_NOT_FOUND"
        )
    return security.id


@router.post("", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    body: WatchlistCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WatchlistRead:
    watchlist = WatchlistRepository(db).create(
        user_id=user.id, name=body.name, description=body.description
    )
    db.commit()
    return WatchlistRead.model_validate(watchlist)


@router.get("", response_model=list[WatchlistListItem])
def list_watchlists(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WatchlistListItem]:
    repo = WatchlistRepository(db)
    watchlists = repo.list_for_user(user_id=user.id)
    return [
        WatchlistListItem(
            **WatchlistRead.model_validate(w).model_dump(),
            item_count=repo.count_items(watchlist_id=w.id),
        )
        for w in watchlists
    ]


@router.get("/{watchlist_id}", response_model=WatchlistDetailResponse)
def get_watchlist(
    watchlist_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WatchlistDetailResponse:
    watchlist = get_watchlist_for_user(db, watchlist_id=watchlist_id, user_id=user.id)
    detail = get_watchlist_detail(db, watchlist)
    return WatchlistDetailResponse(
        **WatchlistRead.model_validate(watchlist).model_dump(),
        items=[WatchlistItemRead(**vars(item)) for item in detail.items],
    )


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    watchlist_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    watchlist = get_watchlist_for_user(db, watchlist_id=watchlist_id, user_id=user.id)
    WatchlistRepository(db).delete(watchlist)
    db.commit()


@router.post(
    "/{watchlist_id}/items",
    response_model=WatchlistDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_watchlist_item(
    watchlist_id: uuid.UUID,
    body: WatchlistItemAdd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WatchlistDetailResponse:
    watchlist = get_watchlist_for_user(db, watchlist_id=watchlist_id, user_id=user.id)
    security_id = _resolve_security_id_or_404(db, body.ticker)
    WatchlistRepository(db).add_item(watchlist_id=watchlist.id, security_id=security_id)
    db.commit()
    detail = get_watchlist_detail(db, watchlist)
    return WatchlistDetailResponse(
        **WatchlistRead.model_validate(watchlist).model_dump(),
        items=[WatchlistItemRead(**vars(item)) for item in detail.items],
    )


@router.delete("/{watchlist_id}/items/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist_item(
    watchlist_id: uuid.UUID,
    ticker: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    watchlist = get_watchlist_for_user(db, watchlist_id=watchlist_id, user_id=user.id)
    security_id = _resolve_security_id_or_404(db, ticker)
    WatchlistRepository(db).remove_item(watchlist_id=watchlist.id, security_id=security_id)
    db.commit()
