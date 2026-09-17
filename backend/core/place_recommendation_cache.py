from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import uuid4


PLACE_PAGE_SIZE = 6
PLACE_CACHE_TTL_SECONDS = 15 * 60


class PlaceCursorNotFoundError(Exception):
    """존재하지 않는 장소 추천 cursor."""


class PlaceCursorExpiredError(Exception):
    """만료된 장소 추천 cursor."""


@dataclass
class PlaceRecommendationCacheEntry:
    area_name: str
    places: list[dict]
    expires_at: float


@dataclass
class PlaceRecommendationPage:
    area_name: str
    places: list[dict]
    cursor: str | None
    has_more: bool
    next_offset: int | None


_place_cache: dict[str, PlaceRecommendationCacheEntry] = {}
_place_cache_lock = Lock()


def _purge_expired_entries(now: float):
    expired_cursors = [
        cursor
        for cursor, entry in _place_cache.items()
        if entry.expires_at <= now
    ]

    for cursor in expired_cursors:
        del _place_cache[cursor]


def create_place_recommendation_page(
    area_name: str,
    places: list[dict],
    ttl_seconds: int = PLACE_CACHE_TTL_SECONDS,
):
    """후보 pool의 첫 6개를 반환하고 남은 후보를 cache에 보관한다."""

    first_page = places[:PLACE_PAGE_SIZE]
    has_more = len(places) > PLACE_PAGE_SIZE

    if not has_more:
        return PlaceRecommendationPage(
            area_name=area_name,
            places=first_page,
            cursor=None,
            has_more=False,
            next_offset=None,
        )

    cursor = uuid4().hex

    now = monotonic()

    with _place_cache_lock:
        _purge_expired_entries(now)

        _place_cache[cursor] = PlaceRecommendationCacheEntry(
            area_name=area_name,
            places=places,
            expires_at=now + ttl_seconds,
        )

    return PlaceRecommendationPage(
        area_name=area_name,
        places=first_page,
        cursor=cursor,
        has_more=True,
        next_offset=PLACE_PAGE_SIZE,
    )


def get_next_place_recommendation_page(
    cursor: str,
    offset: int,
):
    """cache에 저장된 다음 6개를 외부 API 재호출 없이 반환한다."""

    with _place_cache_lock:
        entry = _place_cache.get(cursor)

        if entry is None:
            raise PlaceCursorNotFoundError

        if entry.expires_at <= monotonic():
            del _place_cache[cursor]
            raise PlaceCursorExpiredError

        page_end = offset + PLACE_PAGE_SIZE
        places = entry.places[offset:page_end]
        has_more = page_end < len(entry.places)
        next_offset = page_end if has_more else None

    return PlaceRecommendationPage(
        area_name=entry.area_name,
        places=places,
        cursor=cursor,
        has_more=has_more,
        next_offset=next_offset,
    )


def clear_place_recommendation_cache():
    """테스트와 운영 점검에서 장소 추천 cache를 비운다."""

    with _place_cache_lock:
        _place_cache.clear()
