# --- deps: compile/install Python dependencies (needs gcc/libpq-dev to
# build a couple of wheels; this stage's tools never reach the runtime
# image) ---
FROM python:3.11-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --user -r requirements.txt

# --- dev: adds dev/test tooling on top of the runtime dependency set;
# this is what infra/docker-compose.yml's `backend`/`worker`/`beat`
# services use for local hot-reload (bind-mounted source, `--reload`) —
# see that file. Never used to build what actually ships. ---
FROM deps AS dev-deps
COPY requirements-dev.txt ./
RUN pip install --user -r requirements-dev.txt

FROM python:3.11-slim AS dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/root/.local/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=dev-deps /root/.local /root/.local
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

# ../ml is copied in by docker-compose build context / bind mount in dev;
# in production images it is installed as a package (see infra docs).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- production: the slim runtime image actually deployed. No compilers,
# no dev/test tooling, no source bind-mount, non-root — see
# docs/deployment.md. `docker build --target production` (the default
# `docker build` target, since it's the last stage). ---
FROM python:3.11-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/home/appuser/.local/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=deps /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . .
RUN chown -R appuser:appuser /home/appuser/.local

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
