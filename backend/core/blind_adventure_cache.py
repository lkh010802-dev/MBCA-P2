from copy import deepcopy
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Callable


BLIND_ADVENTURE_TTL_SECONDS = 10 * 60


class BlindAdventureTokenError(Exception):
    """존재하지 않거나 만료된 블라인드 가챠 token."""


@dataclass
class BlindAdventureCacheEntry:
    result: dict
    expires_at: float
    kind: str


_blind_adventure_cache: dict[str, BlindAdventureCacheEntry] = {}
_blind_adventure_cache_lock = Lock()


def _purge_expired_entries(now: float):
    expired_tokens = [
        token
        for token, entry in _blind_adventure_cache.items()
        if entry.expires_at <= now
    ]
    for token in expired_tokens:
        del _blind_adventure_cache[token]


def store_blind_adventure(
    result: dict,
    *,
    ttl_seconds: int = BLIND_ADVENTURE_TTL_SECONDS,
    kind: str = "single",
    now_fn: Callable[[], float] = monotonic,
    token_fn: Callable[[int], str] = token_urlsafe,
) -> str:
    now = now_fn()
    with _blind_adventure_cache_lock:
        _purge_expired_entries(now)
        token = token_fn(32)
        while token in _blind_adventure_cache:
            token = token_fn(32)
        _blind_adventure_cache[token] = BlindAdventureCacheEntry(
            result=deepcopy(result),
            expires_at=now + ttl_seconds,
            kind=kind,
        )
    return token


def get_blind_adventure(
    token: str,
    *,
    kind: str = "single",
    now_fn: Callable[[], float] = monotonic,
) -> dict:
    now = now_fn()
    with _blind_adventure_cache_lock:
        _purge_expired_entries(now)
        entry = _blind_adventure_cache.get(token)
        if entry is None or entry.kind != kind:
            raise BlindAdventureTokenError
        return deepcopy(entry.result)


def clear_blind_adventure_cache():
    with _blind_adventure_cache_lock:
        _blind_adventure_cache.clear()
