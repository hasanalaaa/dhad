"""Gunicorn production configuration for Dhad's asynchronous FastAPI service."""

from __future__ import annotations

import multiprocessing
import os


def _integer(name: str, default: int, *, minimum: int = 1, maximum: int = 256) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


bind = f"{os.environ.get('DHAD_HOST', '0.0.0.0')}:{_integer('DHAD_PORT', 8010, maximum=65535)}"
workers = _integer("DHAD_WORKERS", min(4, multiprocessing.cpu_count() * 2 + 1), maximum=32)
threads = _integer("DHAD_THREADS", 1, maximum=8)
worker_class = "uvicorn_worker.UvicornWorker"
worker_tmp_dir = "/dev/shm"
# Async Redis clients, event-loop locks, and Pub/Sub readers must be created in
# each worker after fork. Preloading the ASGI app in the Gunicorn master would
# make those resources cross a process boundary.
preload_app = False

backlog = _integer("DHAD_BACKLOG", 2048, maximum=65535)
timeout = _integer("DHAD_TIMEOUT", 60, maximum=600)
graceful_timeout = _integer("DHAD_GRACEFUL_TIMEOUT", 30, maximum=300)
keepalive = _integer("DHAD_KEEPALIVE", 5, maximum=120)
max_requests = _integer("DHAD_MAX_REQUESTS", 5000, maximum=1_000_000)
max_requests_jitter = _integer("DHAD_MAX_REQUESTS_JITTER", 500, minimum=0, maximum=100_000)

errorlog = "-"
loglevel = os.environ.get("DHAD_LOG_LEVEL", "info").lower()
capture_output = True
accesslog = "-" if _boolean("DHAD_ACCESS_LOG", False) else None
# Path only: no query string, request body, headers, API key, or user text.
access_log_format = (
    '%({x-forwarded-for}i)s %(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(L)s'
)

# Avoid leaking process environment or request data through verbose exception
# dumps. Gunicorn still emits operational stack traces to stderr.
proc_name = "dhad-api"
forwarded_allow_ips = os.environ.get("DHAD_FORWARDED_ALLOW_IPS", "127.0.0.1")
