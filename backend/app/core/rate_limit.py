from slowapi import Limiter
from slowapi.util import get_remote_address

# Keyed by client IP. Redis-backed storage (shared across API replicas) is a
# follow-up once the app runs multi-instance; in-memory is correct for a
# single-process dev/demo deployment.
limiter = Limiter(key_func=get_remote_address)
