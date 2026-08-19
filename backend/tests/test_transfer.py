import asyncio

from app.database import get_connection
from app.services.transfer import transfer_once


def test_transfer_once_moves_balance_and_preserves_total(client) -> None:
    async def run_transfer():
        connection = await get_connection("test-transfer")
        try:
            return await transfer_once(
                connection,
                transaction_id="TEST",
                source_id=1,
                destination_id=2,
                amount=100,
                lock_order="source_first",
            )
        finally:
            await connection.close()

    result = asyncio.run(run_transfer())

    assert result.status == "COMMITTED"
    payload = client.get("/api/accounts").json()
    assert [(account["id"], account["balance"]) for account in payload["accounts"]] == [
        (1, 900),
        (2, 1100),
    ]
    assert payload["total_balance"] == 2000
