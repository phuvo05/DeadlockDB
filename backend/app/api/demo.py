import asyncio
import logging

from fastapi import APIRouter, HTTPException
import psycopg

from app.models.schemas import DemoResponse
from app.services.deadlock_demo import (
    run_deadlock_demo,
    run_retry_demo,
    run_safe_ordering_demo,
)
from app.services.coordinator import demo_lock


router = APIRouter(prefix="/api/demo")
logger = logging.getLogger("deadlock_lab.api.demo")
async def _run_demo(runner) -> DemoResponse:
    if demo_lock.locked():
        raise HTTPException(status_code=409, detail="Another demo is already running")
    async with demo_lock:
        try:
            return await runner()
        except HTTPException:
            raise
        except psycopg.OperationalError as exc:
            logger.exception("database unavailable during demo")
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        except Exception as exc:
            logger.exception("demo execution failed")
            raise HTTPException(status_code=500, detail="Demo failed unexpectedly") from exc


@router.post("/deadlock", response_model=DemoResponse)
async def deadlock_demo() -> DemoResponse:
    return await _run_demo(run_deadlock_demo)


@router.post("/safe-ordering", response_model=DemoResponse)
async def safe_ordering_demo() -> DemoResponse:
    return await _run_demo(run_safe_ordering_demo)


@router.post("/retry", response_model=DemoResponse)
async def retry_demo() -> DemoResponse:
    return await _run_demo(run_retry_demo)
