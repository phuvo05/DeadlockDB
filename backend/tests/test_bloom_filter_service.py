import pytest

from app.services.bloom_filter import BloomFilter


def test_new_filter_definitely_excludes_unknown_value() -> None:
    bloom = BloomFilter()

    assert bloom.might_contain("unknown@example.com") is False


def test_inserted_values_never_have_false_negatives() -> None:
    bloom = BloomFilter()
    values = ["alice@example.com", "https://example.com/article/1", "user:1001"]

    for value in values:
        bloom.add(value)

    assert all(bloom.might_contain(value) for value in values)
    assert bloom.inserted_count == len(values)


def test_false_positive_rate_is_bounded_and_grows_with_insertions() -> None:
    small = BloomFilter()
    large = BloomFilter()
    for value in [f"item:{index}" for index in range(20)]:
        large.add(value)

    assert 0 <= small.estimated_false_positive_rate() <= 1
    assert 0 <= large.estimated_false_positive_rate() <= 1
    assert large.estimated_false_positive_rate() > small.estimated_false_positive_rate()


@pytest.mark.parametrize("kwargs", [{"bit_size": 0}, {"hash_count": 0}])
def test_invalid_filter_parameters_are_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        BloomFilter(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [{"bit_size": 1.5}, {"hash_count": 1.5}, {"bit_size": True}],
)
def test_non_integer_filter_parameters_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        BloomFilter(**kwargs)


def test_hash_probes_keep_a_nonzero_effective_step() -> None:
    bloom = BloomFilter()

    assert len(set(bloom._positions("probe:778"))) == bloom.hash_count
