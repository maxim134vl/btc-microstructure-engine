"""Bounded in-memory cache for Shadow Auction (AES0 RAM contract)."""

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class BoundedCache(Generic[K, V]):
    """Fixed-capacity LRU cache. Refuses unbounded growth."""

    def __init__(self, max_items: int = 256) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self.max_items = int(max_items)
        self._data: OrderedDict[K, V] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: K, default: V | None = None) -> V | None:
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: K, value: V) -> None:
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
        else:
            self._data[key] = value
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def keys(self) -> list[K]:
        return list(self._data.keys())
