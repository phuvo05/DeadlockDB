from typing import Any, Literal

from pydantic import BaseModel, Field


class Account(BaseModel):
    id: int
    name: str
    balance: int


class AccountsResponse(BaseModel):
    accounts: list[Account]
    total_balance: int
    invariant_ok: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]


class ResetResponse(AccountsResponse):
    reset: bool = True


class DebugDatabaseResponse(BaseModel):
    postgres_version: str
    database_name: str
    current_connections: int = Field(ge=0)


class TransactionResult(BaseModel):
    transaction_id: str
    source_id: int
    destination_id: int
    amount: int
    status: Literal["COMMITTED", "ROLLED_BACK"]
    attempts: int = 1
    sqlstate: str | None = None
    error: str | None = None
    deadlock_victim: bool = False


class BloomCheckResult(BaseModel):
    value: str
    inserted: bool
    maybe_present: bool
    interpretation: Literal["POSSIBLY_PRESENT", "DEFINITELY_ABSENT"]


class BloomFilterResponse(BaseModel):
    run_id: str
    mode: Literal["bloom-filter"]
    demo_completed: bool
    bit_size: int
    hash_count: int
    inserted_items: list[str]
    checks: list[BloomCheckResult]
    estimated_false_positive_rate: float
    applications: list[str]
    events: list[dict[str, Any]]
    duration_ms: float


class DemoResponse(BaseModel):
    run_id: str
    mode: Literal["deadlock", "safe-ordering", "retry"]
    demo_completed: bool
    deadlock_detected: bool
    victim: str | None = None
    transactions: list[TransactionResult]
    events: list[dict[str, Any]]
    balances: list[Account]
    total_balance: int
    invariant_ok: bool
    duration_ms: float
