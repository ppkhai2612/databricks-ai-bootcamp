"""Lakebase (Databricks-managed Postgres) connection helpers.

Authentication uses a static Postgres connection URL stored in a Databricks
secret scope (``database/lakebase-url``). The secret value is base64-encoded by
the Databricks SDK, so it is decoded before use. This module is framework
agnostic and is reused unchanged by both the FastAPI app and the seed script.
"""

import base64
import os
from contextlib import contextmanager

import psycopg2
from databricks.sdk import WorkspaceClient
from psycopg2.extras import RealDictCursor

_SCOPE = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
_KEY = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")

_w = None


def _client() -> WorkspaceClient:
    """Lazily construct the WorkspaceClient.

    Building it at import time would require Databricks credentials even when
    running locally with ``LAKEBASE_URL`` set, so we defer until it's needed.
    """
    global _w
    if _w is None:
        _w = WorkspaceClient()
    return _w


def _lakebase_url() -> str:
    """Fetch and decode the Lakebase connection URL from the secret scope.

    For local development you can bypass the secret scope entirely by exporting
    ``LAKEBASE_URL`` in your environment (see ``.env.example``).
    """
    env_url = os.environ.get("LAKEBASE_URL")
    if env_url:
        return env_url
    secret = _client().secrets.get_secret(scope=_SCOPE, key=_KEY)
    return base64.b64decode(secret.value).decode("utf-8")


@contextmanager
def get_connection():
    """Yield a psycopg2 connection whose cursors return dict rows."""
    conn = psycopg2.connect(_lakebase_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def run_query(sql, params=None) -> list[dict]:
    """Execute a read query and return all rows as a list of dicts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def run_write(sql, params=None) -> int:
    """Execute a write statement, commit, and return the affected row count."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount