"""Serverless entrypoint; durable PostgreSQL storage is mandatory."""

from app.core.config import settings
from app.main import app as app

if not settings.database_url.startswith("postgresql+psycopg://"):
    raise RuntimeError("Vercel deployments require a PostgreSQL DATABASE_URL")
