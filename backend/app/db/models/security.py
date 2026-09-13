from datetime import datetime

from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.sql_helpers import sql_string_list


class SecurityStatus:
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"

    ALL = (ACTIVE, DELISTED)


class DataSource:
    """Provenance of a security's data — surfaced in every API response and
    the frontend so demo data is never mistaken for real market data."""

    DEMO = "demo"
    EXTERNAL = "external"

    ALL = (DEMO, EXTERNAL)


class Security(Base):
    __tablename__ = "securities"
    __table_args__ = (
        CheckConstraint(
            f"status IN {sql_string_list(SecurityStatus.ALL)}", name="ck_securities_status"
        ),
        CheckConstraint(
            f"data_source IN {sql_string_list(DataSource.ALL)}",
            name="ck_securities_data_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SecurityStatus.ACTIVE)
    data_source: Mapped[str] = mapped_column(String(20), nullable=False, default=DataSource.DEMO)
    extra: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
