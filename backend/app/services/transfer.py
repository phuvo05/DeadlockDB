from dataclasses import dataclass
from typing import Literal

from psycopg.rows import dict_row

from app.services.timeline import Timeline


TransferStatus = Literal["COMMITTED", "ROLLED_BACK"]
LockOrder = Literal["source_first", "ascending"]


class TransferError(Exception):
    """Base error for a transfer that cannot be completed."""


class InsufficientBalanceError(TransferError):
    """Raised when the source account cannot cover the transfer."""


@dataclass
class TransferExecution:
    transaction_id: str
    source_id: int
    destination_id: int
    amount: int
    status: TransferStatus
    sqlstate: str | None = None
    error: str | None = None


async def lock_account(
    connection,
    transaction_id: str,
    account_id: int,
    timeline: Timeline | None = None,
) -> dict:
    if timeline:
        timeline.add(
            transaction_id,
            "LOCK_REQUESTED",
            f"Requesting row lock for account {account_id}",
            account_id=account_id,
        )
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            """
            SELECT id, name, balance
            FROM accounts
            WHERE id = %s
            FOR UPDATE
            """,
            (account_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        raise TransferError(f"Account {account_id} does not exist")
    if timeline:
        timeline.add(
            transaction_id,
            "LOCK_ACQUIRED",
            f"Account {account_id} locked",
            account_id=account_id,
        )
    return dict(row)


async def apply_transfer(
    connection,
    transaction_id: str,
    source_id: int,
    destination_id: int,
    amount: int,
    locked_accounts: dict[int, dict],
    timeline: Timeline | None = None,
) -> None:
    if amount <= 0:
        raise TransferError("Transfer amount must be positive")
    source = locked_accounts[source_id]
    if source["balance"] < amount:
        raise InsufficientBalanceError(
            f"Account {source_id} has insufficient balance for {amount}"
        )
    async with connection.cursor() as cursor:
        await cursor.execute(
            "UPDATE accounts SET balance = balance - %s WHERE id = %s",
            (amount, source_id),
        )
        await cursor.execute(
            "UPDATE accounts SET balance = balance + %s WHERE id = %s",
            (amount, destination_id),
        )
    if timeline:
        timeline.add(
            transaction_id,
            "UPDATE_EXECUTED",
            f"Transferred {amount} from account {source_id} to account {destination_id}",
            source_id=source_id,
            destination_id=destination_id,
            amount=amount,
        )


async def transfer_once(
    connection,
    transaction_id: str,
    source_id: int,
    destination_id: int,
    amount: int,
    lock_order: LockOrder,
    timeline: Timeline | None = None,
) -> TransferExecution:
    if source_id == destination_id:
        raise TransferError("Source and destination accounts must differ")
    if lock_order == "source_first":
        account_ids = [source_id, destination_id]
    else:
        account_ids = sorted((source_id, destination_id))

    await connection.execute("BEGIN")
    if timeline:
        timeline.add(transaction_id, "BEGIN", "Transaction started")
    try:
        locked_accounts = {
            account_id: await lock_account(connection, transaction_id, account_id, timeline)
            for account_id in account_ids
        }
        if timeline:
            timeline.add(
                transaction_id,
                "BALANCE_VALIDATED",
                f"Source balance is {locked_accounts[source_id]['balance']}",
                source_id=source_id,
            )
        await apply_transfer(
            connection,
            transaction_id,
            source_id,
            destination_id,
            amount,
            locked_accounts,
            timeline,
        )
        await connection.commit()
        if timeline:
            timeline.add(transaction_id, "COMMIT", "Transaction committed")
        return TransferExecution(
            transaction_id=transaction_id,
            source_id=source_id,
            destination_id=destination_id,
            amount=amount,
            status="COMMITTED",
        )
    except InsufficientBalanceError as exc:
        await connection.rollback()
        if timeline:
            timeline.add(transaction_id, "ROLLBACK", str(exc))
        return TransferExecution(
            transaction_id=transaction_id,
            source_id=source_id,
            destination_id=destination_id,
            amount=amount,
            status="ROLLED_BACK",
            error=str(exc),
        )
    except Exception:
        await connection.rollback()
        if timeline:
            timeline.add(transaction_id, "ROLLBACK", "Unexpected database error")
        raise
