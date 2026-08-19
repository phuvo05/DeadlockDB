import asyncio
from dataclasses import dataclass
import logging
import random
import time
from uuid import uuid4

import psycopg

from app.api.accounts import read_accounts
from app.database import get_connection
from app.models.schemas import DemoResponse, TransactionResult
from app.services.timeline import Timeline
from app.services.transfer import (
    InsufficientBalanceError,
    apply_transfer,
    lock_account,
    transfer_once,
)


logger = logging.getLogger("deadlock_lab.demo")
MAX_ATTEMPTS = 3
DEMO_TIMEOUT_SECONDS = 10


@dataclass
class TransactionState:
    transaction_id: str
    source_id: int
    destination_id: int
    amount: int
    status: str = "ROLLED_BACK"
    attempts: int = 1
    sqlstate: str | None = None
    error: str | None = None
    deadlock_victim: bool = False

    def as_response(self) -> TransactionResult:
        return TransactionResult(
            transaction_id=self.transaction_id,
            source_id=self.source_id,
            destination_id=self.destination_id,
            amount=self.amount,
            status=self.status,
            attempts=self.attempts,
            sqlstate=self.sqlstate,
            error=self.error,
            deadlock_victim=self.deadlock_victim,
        )


def _new_run(mode: str) -> tuple[str, Timeline, float]:
    run_id = uuid4().hex[:12]
    timeline = Timeline(run_id)
    started = time.monotonic()
    timeline.add("RUN", "RUN_STARTED", f"{mode} demo started", mode=mode)
    return run_id, timeline, started


async def _new_demo_connection(transaction_id: str) -> psycopg.AsyncConnection:
    connection = await get_connection(f"deadlock-lab-{transaction_id}")
    await connection.execute("SET deadlock_timeout = '100ms'")
    return connection


async def _unsafe_transfer(
    state: TransactionState,
    timeline: Timeline,
    first_lock_acquired: asyncio.Event,
    other_first_lock_acquired: asyncio.Event,
) -> TransactionState:
    connection = None
    try:
        connection = await _new_demo_connection(state.transaction_id)
        await connection.execute("BEGIN")
        timeline.add(state.transaction_id, "BEGIN", "Transaction started")

        first = await lock_account(
            connection,
            state.transaction_id,
            state.source_id,
            timeline,
        )
        first_lock_acquired.set()
        await other_first_lock_acquired.wait()

        timeline.add(
            state.transaction_id,
            "LOCK_WAITING",
            f"Requesting account {state.destination_id} while the other transaction owns it",
            account_id=state.destination_id,
        )
        second = await lock_account(
            connection,
            state.transaction_id,
            state.destination_id,
            timeline,
        )
        locked_accounts = {
            state.source_id: first,
            state.destination_id: second,
        }
        timeline.add(
            state.transaction_id,
            "BALANCE_VALIDATED",
            f"Source balance is {first['balance']}",
            source_id=state.source_id,
        )
        await apply_transfer(
            connection,
            state.transaction_id,
            state.source_id,
            state.destination_id,
            state.amount,
            locked_accounts,
            timeline,
        )
        await connection.commit()
        state.status = "COMMITTED"
        timeline.add(state.transaction_id, "COMMIT", "Transaction committed")
        return state
    except psycopg.errors.DeadlockDetected as exc:
        state.sqlstate = getattr(exc, "sqlstate", None) or "40P01"
        state.deadlock_victim = True
        state.status = "ROLLED_BACK"
        timeline.add(
            state.transaction_id,
            "DEADLOCK_DETECTED",
            "PostgreSQL detected a circular wait and chose this transaction as victim",
            sqlstate=state.sqlstate,
        )
        if connection is not None:
            await connection.rollback()
        timeline.add(
            state.transaction_id,
            "ROLLBACK",
            "Deadlock victim rolled back",
            sqlstate=state.sqlstate,
        )
        return state
    except Exception:
        if connection is not None:
            await connection.rollback()
        timeline.add(
            state.transaction_id,
            "ROLLBACK",
            "Unexpected database error caused rollback",
        )
        raise
    finally:
        if connection is not None:
            await connection.close()


async def _run_unsafe_pair(
    timeline: Timeline,
) -> list[TransactionState]:
    t1_locked = asyncio.Event()
    t2_locked = asyncio.Event()
    states = [
        TransactionState("T1", source_id=1, destination_id=2, amount=100),
        TransactionState("T2", source_id=2, destination_id=1, amount=200),
    ]
    tasks = [
        asyncio.create_task(_unsafe_transfer(states[0], timeline, t1_locked, t2_locked)),
        asyncio.create_task(_unsafe_transfer(states[1], timeline, t2_locked, t1_locked)),
    ]
    try:
        return await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=DEMO_TIMEOUT_SECONDS,
        )
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def run_deadlock_demo() -> DemoResponse:
    run_id, timeline, started = _new_run("deadlock")
    states = await _run_unsafe_pair(timeline)
    snapshot = await read_accounts()
    victim = next((state.transaction_id for state in states if state.deadlock_victim), None)
    timeline.add("RUN", "RUN_FINISHED", "Deadlock demo finished")
    return DemoResponse(
        run_id=run_id,
        mode="deadlock",
        demo_completed=True,
        deadlock_detected=any(state.deadlock_victim for state in states),
        victim=victim,
        transactions=[state.as_response() for state in states],
        events=timeline.events,
        balances=snapshot.accounts,
        total_balance=snapshot.total_balance,
        invariant_ok=snapshot.invariant_ok,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )


async def run_safe_ordering_demo() -> DemoResponse:
    raise NotImplementedError


async def run_retry_demo() -> DemoResponse:
    raise NotImplementedError
