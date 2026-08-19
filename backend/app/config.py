from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_name: str = "postgres-deadlock-lab"


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/deadlock_demo",
        )
    )


settings = load_settings()
