import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import DemoResponse
from app.services.deadlock_demo import run_deadlock_demo


router = APIRouter(prefix="/api/demo")
logger = logging.getLogger("deadlock_lab.api.demo")
demo_lock = asyncio.Lock()


async def _run_demo(runner) -> DemoResponse:
    if demo_lock.locked():
        raise HTTPException(status_code=409, detail="Another demo is already running")
    async with demo_lock:
        try:
            return await runner()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("demo execution failed")
            raise HTTPException(status_code=500, detail="Demo failed unexpectedly") from exc


@router.post("/deadlock", response_model=DemoResponse)
async def deadlock_demo() -> DemoResponse:
    return await _run_demo(run_deadlock_demo)
