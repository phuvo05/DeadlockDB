import time
from uuid import uuid4

from app.models.schemas import BloomCheckResult, BloomFilterResponse
from app.services.bloom_filter import BloomFilter
from app.services.timeline import Timeline


INSERTED_ITEMS = (
    "alice@example.com",
    "bob@example.com",
    "https://example.com/articles/1",
    "content:sha256:demo-001",
    "user:1001",
)
CHECK_ITEMS = (
    ("alice@example.com", True),
    ("https://example.com/articles/1", True),
    ("carol@example.com", False),
    ("content:sha256:unknown", False),
)
APPLICATIONS = (
    "Cache/database lookup guard",
    "Email or URL duplicate detection",
    "Duplicate work filtering in ingestion pipelines",
    "Rate-limit and abuse pre-check",
)


async def run_bloom_filter_demo() -> BloomFilterResponse:
    run_id = uuid4().hex[:12]
    timeline = Timeline(run_id)
    started = time.monotonic()
    bloom = BloomFilter()

    timeline.add("BLOOM", "RUN_STARTED", "Bloom Filter demo started")
    for value in INSERTED_ITEMS:
        bloom.add(value)
    timeline.add(
        "BLOOM",
        "ITEMS_INSERTED",
        f"Inserted {len(INSERTED_ITEMS)} sample values into the bit array",
        inserted_count=len(INSERTED_ITEMS),
    )

    checks: list[BloomCheckResult] = []
    for value, inserted in CHECK_ITEMS:
        maybe_present = bloom.might_contain(value)
        interpretation = (
            "POSSIBLY_PRESENT" if maybe_present else "DEFINITELY_ABSENT"
        )
        checks.append(
            BloomCheckResult(
                value=value,
                inserted=inserted,
                maybe_present=maybe_present,
                interpretation=interpretation,
            )
        )
        timeline.add(
            "BLOOM",
            "MEMBERSHIP_CHECKED",
            f"Checked {value}: {interpretation}",
            value=value,
            inserted=inserted,
            maybe_present=maybe_present,
        )

    timeline.add("BLOOM", "RUN_FINISHED", "Bloom Filter demo finished")
    return BloomFilterResponse(
        run_id=run_id,
        mode="bloom-filter",
        demo_completed=True,
        bit_size=bloom.bit_size,
        hash_count=bloom.hash_count,
        inserted_items=list(INSERTED_ITEMS),
        checks=checks,
        estimated_false_positive_rate=bloom.estimated_false_positive_rate(),
        applications=list(APPLICATIONS),
        events=timeline.events,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
