from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    dashboard,
    jobs,
    macro,
    market_data,
    models,
    news,
    portfolios,
    research,
    screener,
    stocks,
    system,
    users,
    watchlists,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
api_router.include_router(market_data.router, prefix="/market-data", tags=["market-data"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(news.router, prefix="/news", tags=["news"])
api_router.include_router(screener.router, prefix="/screener", tags=["screener"])
api_router.include_router(watchlists.router, prefix="/watchlists", tags=["watchlists"])
api_router.include_router(portfolios.router, prefix="/portfolios", tags=["portfolios"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(macro.router, prefix="/macro", tags=["macro"])
api_router.include_router(system.router, prefix="/system", tags=["system"])

# Further resource routers (reports) are registered here as each later
# phase implements them.
