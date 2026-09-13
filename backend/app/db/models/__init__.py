"""Import every model module here so it registers on Base.metadata.

Required both for Alembic autogenerate (see alembic/env.py) and so that
relationship/FK targets resolve regardless of import order elsewhere.
"""

from app.db.models.alert import Alert, AlertEvent
from app.db.models.audit_log import AuditLog
from app.db.models.auth_session import AuthSession
from app.db.models.fundamental import Fundamental
from app.db.models.job import Job
from app.db.models.macro_observation import MacroObservation
from app.db.models.news import ArticleSecurity, NewsArticle, NewsSentiment
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.portfolio import Portfolio, Transaction
from app.db.models.prediction import Prediction
from app.db.models.price_bar import PriceBar
from app.db.models.security import Security
from app.db.models.user import User
from app.db.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Alert",
    "AlertEvent",
    "ArticleSecurity",
    "AuditLog",
    "AuthSession",
    "Fundamental",
    "Job",
    "MacroObservation",
    "NewsArticle",
    "NewsSentiment",
    "PasswordResetToken",
    "Portfolio",
    "Prediction",
    "PriceBar",
    "Security",
    "Transaction",
    "User",
    "Watchlist",
    "WatchlistItem",
]
