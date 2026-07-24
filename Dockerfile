# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
    && python -m pip wheel --wheel-dir /wheels ".[server,production]"

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DHAD_HOST=0.0.0.0 \
    DHAD_PORT=8010 \
    DHAD_RATE_LIMIT_ENABLED=true \
    DHAD_RATE_LIMIT_REQUESTS=120 \
    DHAD_RATE_LIMIT_WINDOW_SECONDS=60 \
    DHAD_MAX_TEXT_CHARACTERS=50000 \
    DHAD_MAX_REQUEST_BYTES=262144 \
    DHAD_SYNC_MAX_PAYLOAD_BYTES=262144 \
    DHAD_SYNC_MAX_PEERS=128 \
    DHAD_SYNC_OUTGOING_QUEUE=256 \
    DHAD_SYNC_SEND_TIMEOUT_SECONDS=5 \
    DHAD_SYNC_MESSAGES_PER_WINDOW=240 \
    DHAD_SYNC_RATE_WINDOW_SECONDS=60 \
    DHAD_SYNC_RECOVERY_LIMIT=1000

RUN groupadd --gid 10001 dhad \
    && useradd --uid 10001 --gid dhad --create-home --shell /usr/sbin/nologin dhad

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels "dhad[server,production]" \
    && rm -rf /wheels
COPY --chown=dhad:dhad gunicorn_conf.py /app/gunicorn_conf.py

USER dhad
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "from urllib.request import urlopen; r=urlopen('http://127.0.0.1:8010/api/health', timeout=3); raise SystemExit(0 if r.status == 200 else 1)"

CMD ["gunicorn", "--config", "/app/gunicorn_conf.py", "dhad.server:app"]
