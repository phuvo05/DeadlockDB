import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_database() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/deadlock_demo",
    )
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            UPDATE accounts
            SET balance = CASE id
                WHEN 1 THEN 1000
                WHEN 2 THEN 1000
            END
            WHERE id IN (1, 2)
            """
        )
        connection.commit()
