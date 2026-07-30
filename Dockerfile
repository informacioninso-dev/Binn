FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt ./
RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels -r requirements.lock.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2 \
    PYTHONMALLOC=malloc

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt ./
COPY --from=builder /wheels /wheels
RUN pip install --upgrade pip \
    && pip install --no-index --find-links=/wheels -r requirements.lock.txt \
    && rm -rf /wheels

COPY . .

RUN chmod +x deploy/entrypoint.sh deploy/release.sh deploy/backup_db.sh deploy/restore_db.sh deploy/smoke_test.sh

ENV DJANGO_SETTINGS_MODULE=config.settings \
    STATIC_ROOT=/app/staticfiles \
    MEDIA_ROOT=/app/media

EXPOSE 8007

ENTRYPOINT ["./deploy/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8007", "config.asgi:application"]