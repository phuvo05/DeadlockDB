from hashlib import sha1, sha256
from math import exp


class BloomFilter:
    """A deterministic in-memory Bloom Filter for educational demos."""

    def __init__(self, bit_size: int = 1024, hash_count: int = 4) -> None:
        if isinstance(bit_size, bool) or not isinstance(bit_size, int) or bit_size <= 0:
            raise ValueError("bit_size must be positive")
        if isinstance(hash_count, bool) or not isinstance(hash_count, int) or hash_count <= 0:
            raise ValueError("hash_count must be positive")
        self._bit_size = bit_size
        self._hash_count = hash_count
        self._bits = bytearray((bit_size + 7) // 8)
        self._inserted_count = 0

    @property
    def bit_size(self) -> int:
        return self._bit_size

    @property
    def hash_count(self) -> int:
        return self._hash_count

    @property
    def inserted_count(self) -> int:
        return self._inserted_count

    def add(self, value: str) -> None:
        for position in self._positions(value):
            byte_index, mask = divmod(position, 8)
            self._bits[byte_index] |= 1 << mask
        self._inserted_count += 1

    def might_contain(self, value: str) -> bool:
        return all(
            self._bits[byte_index] & (1 << mask)
            for byte_index, mask in (divmod(position, 8) for position in self._positions(value))
        )

    def estimated_false_positive_rate(self) -> float:
        if self._inserted_count == 0:
            return 0.0
        exponent = -self._hash_count * self._inserted_count / self._bit_size
        return (1 - exp(exponent)) ** self._hash_count

    def _positions(self, value: str) -> list[int]:
        encoded = value.encode("utf-8")
        digest = sha256(encoded).digest()
        secondary = sha1(encoded).digest()
        hash_a = int.from_bytes(digest[:8], "big")
        hash_b = int.from_bytes(secondary[:8], "big") % self._bit_size or 1
        return [
            (hash_a + index * hash_b) % self._bit_size
            for index in range(self._hash_count)
        ]
