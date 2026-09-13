"""The one Celery application instance for the whole backend.

Run a worker with: `celery -A app.workers.celery_app worker --loglevel=info`
(see infra/docker-compose.yml's `worker` service). Each task module under
`app/workers/tasks/` must be listed in `include` below — explicit rather
than autodiscovery, since `app/workers/tasks/` is itself the tasks package
(not a parent package containing one named `tasks`), which is the layout
Celery's `autodiscover_tasks` expects.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "alphalens",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks.market_data",
        "app.workers.tasks.news",
        "app.workers.tasks.alerts",
        "app.workers.tasks.predictions",
        "app.workers.tasks.retraining",
        "app.workers.tasks.fundamentals",
        "app.workers.tasks.macro",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    # --- Phase 10 production hardening ---------------------------------
    # A task is acknowledged only after it finishes, not the moment a
    # worker picks it up — a worker that crashes mid-task gets its task
    # redelivered to another worker rather than silently losing it. Safe
    # here specifically because every task is written to be idempotent
    # under redelivery: market-data ingestion upserts by (security_id,
    # ts), alert evaluation is guarded by a DB row lock + cooldown,
    # portfolio transactions require an idempotency key, and prediction
    # evaluation only ever touches rows that are still `evaluated_at IS
    # NULL` — a re-run naturally does nothing to an already-evaluated row.
    task_acks_late=True,
    # Complements `task_acks_late`: a task whose worker process is killed
    # (OOM, deploy, crash) is requeued rather than counted as silently
    # successful.
    task_reject_on_worker_lost=True,
    # One task at a time per worker process — a long retraining run must
    # never block that worker from also picking up short, latency-
    # sensitive tasks (alert evaluation, ingestion) queued behind it. Run
    # more worker *processes* (docker-compose's `worker` service already
    # supports `--concurrency`) for parallelism, not a larger prefetch.
    worker_prefetch_multiplicity=1,
    # A hard ceiling on any single task's runtime — a stuck task (e.g. a
    # hung network call to a future real market-data vendor) can no
    # longer occupy a worker forever. Generous enough to comfortably cover
    # `models.retrain` (this deployment's slowest task by a wide margin);
    # short tasks finish in a small fraction of this.
    task_time_limit=1800,
    task_soft_time_limit=1700,
    # Celery Beat: the smallest production-appropriate scheduling
    # primitive already available in this stack — no new queueing system
    # (see docs/decisions.md's Phase 9 ADR). Run with:
    # `celery -A app.workers.celery_app beat --loglevel=info` alongside a
    # worker. `task_always_eager=True` (used in tests) never runs Beat —
    # tests call `evaluate_all_alerts`/`evaluate_alerts_task` directly.
    # `models.retrain` is deliberately NOT scheduled here — it's a manual/
    # administrative trigger only (`POST /models/retrain`), since it's
    # compute-heavy with no natural fixed cadence this deployment needs
    # yet (see docs/decisions.md's Phase 10 ADR).
    beat_schedule={
        "evaluate-alerts": {
            "task": "alerts.evaluate",
            "schedule": settings.alert_evaluation_interval_seconds,
        },
        "evaluate-predictions": {
            "task": "predictions.evaluate",
            "schedule": settings.prediction_evaluation_interval_seconds,
        },
    },
)
