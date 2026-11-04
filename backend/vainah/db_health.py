"""Read-only database connectivity check; never returns or logs credentials."""
from __future__ import annotations

import asyncio
import os

import psycopg


async def _ping(database_url: str) -> None:
    # No migrations or writes: simple connectivity check.
    async with await psycopg.AsyncConnection.connect(
        database_url, connect_timeout=3, autocommit=True
    ) as connection, connection.cursor() as cursor:
        await cursor.execute("SELECT 1")
        if (await cursor.fetchone()) != (1,):
            raise RuntimeError("DB_PING_FAILED")


async def database_status() -> dict[str, str]:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return {
            "status": "not_connected",
            "message": "DATABASE_URL не задана для Python-сервиса Render.",
        }
    if not database_url.startswith(("postgresql://", "postgres://")):
        return {
            "status": "error",
            "message": "DATABASE_URL имеет неверный формат PostgreSQL.",
        }
    try:
        await asyncio.wait_for(_ping(database_url), timeout=6)
    except (psycopg.Error, OSError, TimeoutError, ValueError, RuntimeError):
        # Provider exceptions may contain the connection string, host or username.
        # Do not emit them to responses or logs.
        return {
            "status": "error",
            "message": "Не удалось подтвердить соединение с PostgreSQL.",
        }
    return {
        "status": "ok",
        "message": "PostgreSQL отвечает на проверочный запрос SELECT 1.",
    }
