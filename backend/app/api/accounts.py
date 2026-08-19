import logging

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from app.database import get_connection
from app.models.schemas import (
    AccountsResponse,
    DebugDatabaseResponse,
    HealthResponse,
    ResetResponse,
)
from app.services.coordinator import demo_lock


router = APIRouter(prefix="/api")
logger = logging.getLogger("deadlock_lab.api")


async def read_accounts() -> AccountsResponse:
    connection = await get_connection("deadlock-lab-read")
    try:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT id, name, balance FROM accounts ORDER BY id"
            )
            rows = await cursor.fetchall()
            await cursor.execute("SELECT COALESCE(SUM(balance), 0) AS total_balance FROM accounts")
            total_balance = int((await cursor.fetchone())["total_balance"])
        await connection.commit()
    finally:
        await connection.close()

    accounts = [dict(row) for row in rows]
    return AccountsResponse(
        accounts=accounts,
        total_balance=total_balance,
        invariant_ok=total_balance == 2000,
    )


async def reset_accounts() -> AccountsResponse:
    connection = await get_connection("deadlock-lab-reset")
    try:
        await connection.execute(
            """
            UPDATE accounts
            SET balance = CASE id
                WHEN 1 THEN 1000
                WHEN 2 THEN 1000
            END
            WHERE id IN (1, 2)
            """
        )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    return await read_accounts()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    connection = None
    try:
        connection = await get_connection("deadlock-lab-health")
        await connection.execute("SELECT 1")
        await connection.commit()
        return HealthResponse(status="ok", database="connected")
    except Exception as exc:
        logger.exception("database health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    finally:
        if connection is not None:
            await connection.close()


@router.get("/accounts", response_model=AccountsResponse)
async def accounts() -> AccountsResponse:
    try:
        return await read_accounts()
    except Exception as exc:
        logger.exception("account read failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.post("/reset", response_model=ResetResponse)
async def reset() -> ResetResponse:
    if demo_lock.locked():
        raise HTTPException(status_code=409, detail="Another demo is already running")
    try:
        async with demo_lock:
            result = await reset_accounts()
        return ResetResponse(**result.model_dump())
    except Exception as exc:
        logger.exception("account reset failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/debug/db", response_model=DebugDatabaseResponse)
async def debug_database() -> DebugDatabaseResponse:
    connection = None
    try:
        connection = await get_connection("deadlock-lab-debug")
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """
                SELECT
                    version() AS postgres_version,
                    current_database() AS database_name,
                    (
                        SELECT count(*)
                        FROM pg_stat_activity
                        WHERE datname = current_database()
                    ) AS current_connections
                """
            )
            row = await cursor.fetchone()
        await connection.commit()
        return DebugDatabaseResponse(**row)
    except Exception as exc:
        logger.exception("database debug query failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    finally:
        if connection is not None:
            await connection.close()
