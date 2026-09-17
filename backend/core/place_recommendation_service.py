from datetime import date, datetime
from map_service import (
    get_region_from_coordinates,
    search_places_by_category,
    search_places_by_keyword,
)

from tour_service import (
    get_tour_sigungu_code,
    get_latest_hub_places,
    add_distance_to_places,
    filter_places_by_distance,
)

from place_ranking import (
    add_place_ranking_scores,
    sort_places_by_score,
)
from place_space import classify_place_space
from seoul_culture_service import (
    SEOUL_TIMEZONE,
    SeoulCultureAPIError,
    calculate_distance_m,
    get_nearby_current_exhibitions,
)
from popup_service import PopupDataError, load_current_popup_places as load_popup_places

POPUP_MAX_DISTANCE_M = 2000
POPUP_ACTIVITIES = frozenset({
    "shopping", "entertainment", "food", "cafe", "culture",
})

# 우리 서비스 활동 카테고리 → Kakao 장소 카테고리 코드
KAKAO_ACTIVITY_CATEGORY_CODES = {
    "food": "FD6",
    "cafe": "CE7",
    "culture": "CT1",
    "walk": "AT4",
}

WALK_PRIMARY_CATEGORY_KEYWORDS = (
    "도보여행",
    "둘레길",
    "숲",
    "수목원",
    "식물원",
    "산",
    "강",
    "호수",
    "저수지",
)
WALK_SECONDARY_CATEGORY_KEYWORDS = (
    "테마거리",
    "전망대",
)
WALK_EXCLUDED_CATEGORY_KEYWORDS = (
    "먹자골목",
    "카페거리",
    "스포츠시설",
    "눈썰매장",
    "섬",
)

# TourAPI 관광지 중분류 → 우리 서비스 활동 카테고리
TOUR_ACTIVITY_CATEGORY_MAP = {
    "문화관광": "culture",
    "역사관광": "culture",
    "쇼핑": "shopping",
    "레저스포츠": "entertainment",
}
TOUR_PLACE_ACTIVITIES = frozenset(
    TOUR_ACTIVITY_CATEGORY_MAP.values()
)

# 실제 provider mapping으로 후보를 확보할 수 있는 activity 순서
SUPPORTED_PLACE_ACTIVITIES = [
    "food",
    "cafe",
    "walk",
    "culture",
    "entertainment",
    "shopping",
    "drink",
]


def filter_walk_kakao_places(places: list[dict]):
    """AT4 후보에서 산책에 맞는 장소만 단계적으로 남긴다."""

    def has_category(place, keywords):
        category_tokens = {
            token.strip()
            for part in (place.get("category_name") or "").split(">")
            for token in part.split(",")
        }
        return not category_tokens.isdisjoint(keywords)

    eligible_places = [
        place
        for place in places
        if not has_category(
            place,
            WALK_EXCLUDED_CATEGORY_KEYWORDS,
        )
    ]

    primary_places = [
        place
        for place in eligible_places
        if has_category(
            place,
            WALK_PRIMARY_CATEGORY_KEYWORDS,
        )
    ]

    if primary_places:
        return primary_places

    return [
        place
        for place in eligible_places
        if has_category(
            place,
            WALK_SECONDARY_CATEGORY_KEYWORDS,
        )
    ]

def normalize_place_name(name: str | None):
    """
    장소 중복 비교를 위해 장소명의 표기 차이를 정리한다.

    예:
    CGV 홍대
    CGV/홍대
    → cgv홍대
    """

    if not name:
        return ""

    return (
        name
        .lower()
        .replace(" ", "")
        .replace("/", "")
    )

def remove_duplicate_places(
    places: list[dict],
    max_distance_m: int = 50,
):
    """
    서로 다른 외부 API에서 같은 장소가 중복으로 들어오는 경우를 제거한다.

    중복 판단 기준:
    1. 정규화한 장소명이 동일하고
    2. 두 장소의 좌표가 충분히 가까운 경우

    현재는 같은 이름의 체인점이 다른 지역에 있을 수 있으므로
    이름만으로는 중복 처리하지 않는다.
    """

    unique_places = []

    for place in places:
        place_name = normalize_place_name(
            place.get("name")
        )

        is_duplicate = False

        for saved_place in unique_places:
            saved_name = normalize_place_name(
                saved_place.get("name")
            )

            if place_name != saved_name:
                continue

            # 위도 약 1도 ≈ 111km를 이용한
            # 중복 판정용 간단한 좌표 거리 계산
            latitude_distance_m = (
                abs(
                    place["latitude"]
                    - saved_place["latitude"]
                )
                * 111000
            )

            longitude_distance_m = (
                abs(
                    place["longitude"]
                    - saved_place["longitude"]
                )
                * 88000
            )

            if (
                latitude_distance_m <= max_distance_m
                and longitude_distance_m <= max_distance_m
            ):
                is_duplicate = True
                break

        if not is_duplicate:
            unique_places.append(place)

    return unique_places


def normalize_kakao_places(
    places: list[dict],
    activity: str,
):
    """
    Kakao Local API 장소 데이터를
    우리 서비스 내부 공통 장소 형식으로 변환한다.
    """

    normalized_places = []

    for place in places:

        normalized_places.append({
            "source": "kakao",

            # Kakao 장소 고유 ID
            "source_id": place.get("id"),

            # 장소명
            "name": place.get("place_name"),

            # 좌표
            "latitude": float(place["y"]),
            "longitude": float(place["x"]),

            # 우리 서비스 내부 활동 카테고리
            "category": activity,

            # Kakao에서 제공하는 상세 카테고리
            "category_detail": place.get(
                "category_name"
            ),

            # 주소
            "address": (
                place.get("road_address_name")
                or place.get("address_name")
            ),

            # 기준 좌표와의 거리(m)
            "distance_m": (
                int(place["distance"])
                if place.get("distance")
                else None
            ),
        })

    return normalized_places

def normalize_tour_places(
    places: list[dict],
):
    """
    TourAPI 장소 데이터를
    우리 서비스 내부 공통 장소 형식으로 변환한다.
    """

    normalized_places = []

    for place in places:

        # 좌표가 없는 장소는 실제 장소 추천에 사용할 수 없으므로 제외한다.
        if not place.get("mapX") or not place.get("mapY"):
            continue

        normalized_places.append({
            "source": "tour",

            # 현재 TourAPI 응답에는 별도 장소 ID를
            # 안정적으로 사용하지 않으므로 None으로 둔다.
            "source_id": None,

            # 장소명
            "name": place.get("hubTatsNm"),

            # 좌표
            "latitude": float(place["mapY"]),
            "longitude": float(place["mapX"]),

            # TourAPI 중분류를 우리 서비스 활동 카테고리로 변환한다.
            "category": TOUR_ACTIVITY_CATEGORY_MAP.get(
                place.get("hubCtgryMclsNm")
            ),

            # TourAPI의 관광지 중분류
            "category_detail": place.get(
                "hubCtgryMclsNm"
            ),

            # TourAPI에서 제공하는 중심관광지 순위
            "hub_rank": (
                int(place["hubRank"])
                if place.get("hubRank")
                else None
            ),

            # 현재 사용 중인 API 응답에서는
            # 공통 주소 필드를 사용하지 않는다.
            "address": None,

            # 추천 지역 중심 좌표와의 거리(m)
            "distance_m": (
                round(
                    place["poi_distance_km"] * 1000
                )
                if place.get("poi_distance_km") is not None
                else None
            ),
        })

    return normalized_places


def filter_current_nearby_popup_places(
    places: list[dict],
    active_activities: list[str],
    latitude: float,
    longitude: float,
    reference_date: date | None = None,
):
    """현재 진행 중이며 중심 좌표 2km 안인 팝업만 남긴다."""

    today = reference_date or datetime.now(SEOUL_TIMEZONE).date()
    filtered_places = []

    for place in places:
        if place.get("category") not in active_activities:
            continue

        try:
            start_at = date.fromisoformat(place.get("start_at"))
            end_at = date.fromisoformat(place.get("end_at"))
        except (TypeError, ValueError):
            continue

        if not start_at <= today <= end_at:
            continue

        distance_m = calculate_distance_m(
            latitude,
            longitude,
            place["latitude"],
            place["longitude"],
        )

        if distance_m > POPUP_MAX_DISTANCE_M:
            continue

        nearby_place = place.copy()
        nearby_place["distance_m"] = distance_m
        filtered_places.append(nearby_place)

    return filtered_places


def resolve_place_activities(
    activities: list[str],
):
    """
    실제 provider mapping이 있는 activity만 중복 없이 반환한다.

    사용자가 activity를 지정하지 않으면 현재 provider가 지원하는
    전체 activity를 열어둔다.
    """

    requested_activities = (
        activities
        if activities
        else SUPPORTED_PLACE_ACTIVITIES
    )

    return list(dict.fromkeys(
        activity
        for activity in requested_activities
        if activity in SUPPORTED_PLACE_ACTIVITIES
    ))


def build_personalized_activity_order(
    activity_order: list[str],
    activity_preferences: dict[str, int] | None,
):
    priorities = {4: 1, 5: 2}
    preferences = activity_preferences or {}

    return sorted(
        activity_order,
        key=lambda activity: -priorities.get(
            preferences.get(activity),
            0,
        ),
    )


def order_places_by_activity_round_robin(
    places: list[dict],
    activity_order: list[str],
):
    """
    activity 내부에서는 거리순을 유지하고 activity 사이에서는
    후보가 소진될 때까지 round-robin 순서로 장소를 배치한다.
    """

    places_by_activity = {
        activity: []
        for activity in activity_order
    }

    for place in places:
        category = place.get("category")

        if category in places_by_activity:
            places_by_activity[category].append(place)

    for activity, activity_places in places_by_activity.items():
        places_by_activity[activity] = sort_places_by_score(
            activity_places
        )

    ordered_places = []

    while any(places_by_activity.values()):
        for activity in activity_order:
            activity_places = places_by_activity[activity]

            if activity_places:
                ordered_places.append(
                    activity_places.pop(0)
                )

    return ordered_places


def finalize_recommended_places(
    places: list[dict],
    activity_order: list[str],
    space_preference: str | None = None,
):
    """
    수집이 끝난 장소 후보에 공통 후처리를 적용한다.

    정상 경로와 fallback 경로 모두 중복 제거, 점수 계산,
    activity 내부 정렬과 round-robin을 동일하게 적용한다.
    """

    unique_places = remove_duplicate_places(
        places
    )

    classified_places = [
        {
            **place,
            **classify_place_space(place),
        }
        for place in unique_places
    ]

    scored_places = add_place_ranking_scores(
        classified_places,
        space_preference,
    )

    return order_places_by_activity_round_robin(
        scored_places,
        activity_order,
    )


def recommend_places(
    area_name: str,
    latitude: float,
    longitude: float,
    activities: list[str],
    companions: list[str],
    budget_max: int | None,
    budget_preference: str | None,
    space_preference: str | None,
    activity_preferences: dict[str, int] | None = None,
):
    """
    추천된 지역을 기준으로 실제 방문 장소를 추천한다.

    현재 지역 추천 로직과 실제 장소 추천 로직을 분리하기 위한
    장소 추천 전용 서비스 함수다.

    이후 이 함수 안에서 다음 흐름을 연결한다.

    지역 좌표
    → 행정구역 확인
    → 외부 장소 API 후보 조회
    → 거리 필터
    → 사용자 활동 조건 반영
    → 장소 Ranking
    → 최종 장소 반환
    """

    active_activities = resolve_place_activities(
        activities
    )
    personalized_activity_order = build_personalized_activity_order(
        active_activities,
        activity_preferences,
    )

    # Kakao에서 검색 가능한 활동의 실제 장소 후보를 조회한다.
    normalized_kakao_places = []

    for activity in active_activities:
        try:
            if activity == "drink":
                kakao_places = search_places_by_keyword(
                    latitude=latitude,
                    longitude=longitude,
                    query="술집",
                    radius=2000,
                    size=15,
                )
            else:
                category_code = KAKAO_ACTIVITY_CATEGORY_CODES.get(
                    activity
                )

                if category_code is None:
                    continue

                kakao_places = search_places_by_category(
                    latitude=latitude,
                    longitude=longitude,
                    category_code=category_code,
                    radius=2000,
                    size=15,
                )

                if activity == "walk":
                    kakao_places = filter_walk_kakao_places(
                        kakao_places
                    )

        except Exception:
            # 특정 Kakao 카테고리 조회에 실패하더라도
            # 다른 활동 및 TourAPI 후보 조회는 계속 진행한다.
            continue

        normalized_kakao_places.extend(
            normalize_kakao_places(
                kakao_places,
                activity
            )
        )

    normalized_seoul_culture_places = []

    if "culture" in active_activities:
        try:
            normalized_seoul_culture_places = (
                get_nearby_current_exhibitions(
                    latitude=latitude,
                    longitude=longitude,
                    max_distance_m=2000,
                )
            )
        except SeoulCultureAPIError:
            normalized_seoul_culture_places = []

    normalized_popup_places = []

    if POPUP_ACTIVITIES.intersection(active_activities):
        try:
            normalized_popup_places = filter_current_nearby_popup_places(
                load_popup_places(),
                active_activities,
                latitude,
                longitude,
            )
        except PopupDataError:
            normalized_popup_places = []

    base_places = (
        normalized_kakao_places
        + normalized_seoul_culture_places
        + normalized_popup_places
    )

    if not TOUR_PLACE_ACTIVITIES.intersection(
        active_activities
    ):
        return finalize_recommended_places(
            base_places,
            personalized_activity_order,
            space_preference,
        )

    # 1. 추천 지역의 좌표를 기준으로 행정구역을 확인한다.
    try:
        region = get_region_from_coordinates(
            latitude=latitude,
            longitude=longitude,
        )

    except Exception:
        # Kakao 행정구역 조회에 실패하더라도
        # 이미 조회된 기본 장소 후보가 있다면
        # 해당 후보만으로 랭킹을 계산해서 반환한다.
        return finalize_recommended_places(
            base_places,
            personalized_activity_order,
            space_preference,
        )

    # 행정구역을 찾지 못하더라도
    # 이미 조회된 기본 장소 후보는 반환한다.
    if region is None:
        return finalize_recommended_places(
            base_places,
            personalized_activity_order,
            space_preference,
        )

    # 2. 행정구 이름을 TourAPI의 시군구 코드로 변환한다.
    sigungu_name = region["sigungu_name"]

    tour_sigungu_code = get_tour_sigungu_code(
        sigungu_name
    )

    # TourAPI에서 지원하는 시군구 코드가 없더라도
    # 이미 조회된 기본 장소 후보는 반환한다.
    if tour_sigungu_code is None:
        return finalize_recommended_places(
            base_places,
            personalized_activity_order,
            space_preference,
        )

    # 3. 확인된 자치구를 기준으로 TourAPI에서
    # 실제 장소 후보를 조회한다.
    # TourAPI 호출에 실패하더라도
    # 이미 조회된 기본 장소 후보는 유지한다.
    try:
        places = get_latest_hub_places(
            gu_code=tour_sigungu_code,
        )

    except Exception:
        return finalize_recommended_places(
            base_places,
            personalized_activity_order,
            space_preference,
        )

    # TourAPI 장소 후보가 없더라도
    # 이미 조회된 기본 장소 후보는 반환한다.
    if not places:
        return finalize_recommended_places(
            base_places,
            personalized_activity_order,
            space_preference,
        )
    
    # 4. 각 장소와 추천 지역 중심 좌표 사이의
    # 직선거리를 계산해 장소 데이터에 추가한다.
    places = add_distance_to_places(
        places=places,
        poi_latitude=latitude,
        poi_longitude=longitude,
    )

    # 5. 추천 지역 중심에서 2km 이내의 장소만 남긴다.
    nearby_places = filter_places_by_distance(
        places=places,
        max_distance_km=2.0,
    )

    # 6. TourAPI 원본 데이터를
    # 서비스 내부 공통 장소 형식으로 변환한다.
    normalized_tour_places = normalize_tour_places(
        nearby_places
    )

    # 7. 사용자가 원하는 활동과 맞는 TourAPI 장소만 남긴다.
    filtered_tour_places = [
        place
        for place in normalized_tour_places
        if place["category"] in active_activities
    ]

    # 8. Kakao와 TourAPI 후보를 합친 뒤
    # 같은 실제 장소가 중복된 경우 하나만 남긴다.
    combined_places = (
        normalized_kakao_places
        + filtered_tour_places
        + normalized_seoul_culture_places
        + normalized_popup_places
    )

    # 9. 정상 경로와 fallback 경로가 같은 정책을 사용하도록
    # 공통 후처리에서 중복 제거, 점수 계산, activity별 정렬,
    # round-robin 순서를 적용한다.
    return finalize_recommended_places(
        combined_places,
        personalized_activity_order,
        space_preference,
    )
