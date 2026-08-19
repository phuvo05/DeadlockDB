from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time
from typing import Any


logger = logging.getLogger("deadlock_lab")


@dataclass
class Timeline:
    run_id: str
    started_at: float = field(default_factory=time.monotonic)
    events: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        transaction: str,
        event: str,
        message: str,
        **details: Any,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "transaction": transaction,
            "event": event,
            "message": message,
            "elapsed_ms": round((time.monotonic() - self.started_at) * 1000, 2),
        }
        item.update(details)
        self.events.append(item)
        log_fields = " ".join(f"{key}={value}" for key, value in item.items() if key != "message")
        logger.info("%s message=%s", log_fields, message)
        return item
