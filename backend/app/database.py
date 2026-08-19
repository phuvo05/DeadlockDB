from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from psycopg import AsyncConnection

from app.config import settings


async def get_connection(application_name: str | None = None) -> AsyncConnection:
    connection = await psycopg.AsyncConnection.connect(settings.database_url)
    if application_name:
        await connection.execute(
            "SELECT set_config('application_name', %s, false)",
            (application_name,),
        )
    return connection


@asynccontextmanager
async def connection_scope(application_name: str | None = None) -> AsyncIterator[AsyncConnection]:
    connection = await get_connection(application_name)
    try:
        yield connection
    finally:
        await connection.close()
