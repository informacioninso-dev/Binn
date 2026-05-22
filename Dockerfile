FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.lock.txt

COPY . .

RUN chmod +x deploy/entrypoint.sh deploy/release.sh deploy/backup_db.sh deploy/restore_db.sh deploy/smoke_test.sh

ENV DJANGO_SETTINGS_MODULE=config.settings \
    STATIC_ROOT=/app/staticfiles \
    MEDIA_ROOT=/app/media

EXPOSE 8007

ENTRYPOINT ["./deploy/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8007", "config.asgi:application"]
