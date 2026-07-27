FROM python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/dataops_observability.db \
    RUN_MIGRATIONS_ON_STARTUP=true

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY alembic.ini ./

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir ".[postgres]" \
    && groupadd --gid 10001 apiuser \
    && useradd --uid 10001 --gid apiuser --no-create-home --shell /usr/sbin/nologin apiuser \
    && install -d -o apiuser -g apiuser -m 0750 /data

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["python", "scripts/start_api.py"]
