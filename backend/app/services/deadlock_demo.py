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


async def _ordered_transfer(
    state: TransactionState,
    timeline: Timeline,
    first_lock_acquired: asyncio.Event,
    second_transaction_requested: asyncio.Event,
    is_first_transaction: bool,
) -> TransactionState:
    connection = None
    try:
        connection = await _new_demo_connection(state.transaction_id)
        await connection.execute("BEGIN")
        timeline.add(state.transaction_id, "BEGIN", "Transaction started")

        if is_first_transaction:
            first = await lock_account(
                connection,
                state.transaction_id,
                1,
                timeline,
            )
            first_lock_acquired.set()
            await second_transaction_requested.wait()
            await asyncio.sleep(0.05)
        else:
            await first_lock_acquired.wait()
            timeline.add(
                state.transaction_id,
                "LOCK_WAITING",
                "Waiting for Account 1 held by T1; this is lock contention, not a deadlock",
                account_id=1,
            )
            second_transaction_requested.set()
            first = await lock_account(
                connection,
                state.transaction_id,
                1,
                timeline,
            )

        second = await lock_account(
            connection,
            state.transaction_id,
            2,
            timeline,
        )
        locked_accounts = {1: first, 2: second}
        timeline.add(
            state.transaction_id,
            "BALANCE_VALIDATED",
            f"Source balance is {locked_accounts[state.source_id]['balance']}",
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


async def run_safe_ordering_demo() -> DemoResponse:
    run_id, timeline, started = _new_run("safe-ordering")
    first_lock_acquired = asyncio.Event()
    second_transaction_requested = asyncio.Event()
    states = [
        TransactionState("T1", source_id=1, destination_id=2, amount=100),
        TransactionState("T2", source_id=2, destination_id=1, amount=200),
    ]
    tasks = [
        asyncio.create_task(
            _ordered_transfer(
                states[0],
                timeline,
                first_lock_acquired,
                second_transaction_requested,
                True,
            )
        ),
        asyncio.create_task(
            _ordered_transfer(
                states[1],
                timeline,
                first_lock_acquired,
                second_transaction_requested,
                False,
            )
        ),
    ]
    try:
        states = await asyncio.wait_for(
            asyncio.gather(*tasks),
            timeout=DEMO_TIMEOUT_SECONDS,
        )
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    snapshot = await read_accounts()
    timeline.add("RUN", "RUN_FINISHED", "Safe ordering demo finished")
    return DemoResponse(
        run_id=run_id,
        mode="safe-ordering",
        demo_completed=True,
        deadlock_detected=False,
        transactions=[state.as_response() for state in states],
        events=timeline.events,
        balances=snapshot.accounts,
        total_balance=snapshot.total_balance,
        invariant_ok=snapshot.invariant_ok,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )


async def run_retry_demo() -> DemoResponse:
    run_id, timeline, started = _new_run("retry")
    states = await _run_unsafe_pair(timeline)
    victim = next((state for state in states if state.deadlock_victim), None)
    if victim is None:
        raise RuntimeError("Retry demo expected a deadlock victim")

    for attempt in range(2, MAX_ATTEMPTS + 1):
        backoff_seconds = (0.05 * (2 ** (attempt - 2))) + random.uniform(0.05, 0.1)
        timeline.add(
            victim.transaction_id,
            "RETRY_SCHEDULED",
            f"Backing off before retry attempt {attempt}",
            attempt=attempt,
            backoff_ms=round(backoff_seconds * 1000, 2),
        )
        await asyncio.sleep(backoff_seconds)
        victim.attempts = attempt
        timeline.add(
            victim.transaction_id,
            "RETRY_STARTED",
            f"Retrying entire transaction, attempt {attempt}",
            attempt=attempt,
        )
        connection = None
        try:
            connection = await _new_demo_connection(victim.transaction_id)
            result = await transfer_once(
                connection,
                transaction_id=victim.transaction_id,
                source_id=victim.source_id,
                destination_id=victim.destination_id,
                amount=victim.amount,
                lock_order="source_first",
                timeline=timeline,
            )
            if result.status == "COMMITTED":
                victim.status = "COMMITTED"
                victim.error = None
                return await _finish_response(
                    run_id,
                    "retry",
                    timeline,
                    started,
                    states,
                )
            victim.error = result.error
            break
        except psycopg.errors.DeadlockDetected as exc:
            victim.sqlstate = getattr(exc, "sqlstate", None) or "40P01"
            timeline.add(
                victim.transaction_id,
                "DEADLOCK_DETECTED",
                "Retry attempt also encountered a deadlock",
                sqlstate=victim.sqlstate,
                attempt=attempt,
            )
            if attempt == MAX_ATTEMPTS:
                raise
        finally:
            if connection is not None:
                await connection.close()

    raise RuntimeError("Retry attempts exhausted without a committed transaction")


async def _finish_response(
    run_id: str,
    mode: str,
    timeline: Timeline,
    started: float,
    states: list[TransactionState],
) -> DemoResponse:
    snapshot = await read_accounts()
    victim = next((state.transaction_id for state in states if state.deadlock_victim), None)
    timeline.add("RUN", "RUN_FINISHED", f"{mode} demo finished")
    return DemoResponse(
        run_id=run_id,
        mode=mode,
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
