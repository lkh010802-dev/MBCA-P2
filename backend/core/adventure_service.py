from secrets import choice
from itertools import combinations

from fastapi import HTTPException

from blind_adventure_cache import (
    BLIND_ADVENTURE_TTL_SECONDS,
    get_blind_adventure,
    store_blind_adventure,
)
from course_order_optimizer import optimize_course_order
from course_routes import calculate_course
from models import (
    AdventureCourseResponse,
    AdventureRequest,
    AdventureResponse,
    CourseCalculationRequest,
    PlaceRecommendRequest,
    SeoulGachaRequest,
)
from place_recommendation_service import recommend_places
from stay_time_validation import (
    IMPOSSIBLE_BY_STAY_TIME,
    validate_selected_places_stay_time,
)


# 실제 방문 가능성을 검증하는 후보 수를 제한해 장소·경로 API 호출 비용을 통제한다.
MAX_GACHA_VALIDATION_CANDIDATES = 3
MAX_COURSE_GACHA_PLACE_CANDIDATES = 20
MAX_COURSE_GACHA_VALIDATION_COMBINATIONS = 3
MIN_COURSE_GACHA_PLACE_DISTANCE_M = 200
RANDOM_QUESTS = {
    "food": (
        "평소 안 먹던 메뉴 하나 골라보기",
        "처음 보는 메뉴 하나 주문해보기",
        "오늘 처음 먹어보는 음식 하나 도전하기",
        "메뉴판에서 가장 궁금한 음식 하나 고르기",
        "함께 온 사람과 서로 메뉴 하나씩 추천해보기",
    ),
    "cafe": (
        "평소 안 먹던 음료 하나 골라보기",
        "디저트 하나 랜덤으로 골라보기",
        "창가나 평소 안 앉던 자리에 앉아보기",
        "음료를 기다리며 주변에서 마음에 드는 소품 찾아보기",
        "오늘 기분을 한 문장으로 적어보기",
    ),
    "walk": (
        "10분 동안 큰길 대신 골목길로 걸어보기",
        "사진 한 장 남기고 싶은 장소 찾아보기",
        "처음 보는 가게 하나 발견해보기",
        "주변에서 가장 마음에 드는 나무 찾아보기",
        "잠시 멈춰 주변 소리 세 가지 들어보기",
    ),
    "culture": (
        "가장 마음에 드는 작품 하나 고르기",
        "가장 오래 보고 싶은 작품 찾아보기",
        "오늘 처음 알게 된 사실 하나 기억해보기",
        "작품 하나에 나만의 제목 붙여보기",
        "전시를 한 문장으로 표현해보기",
    ),
    "entertainment": (
        "평소 안 하던 게임이나 활동 하나 골라보기",
        "첫 번째로 눈에 들어온 콘텐츠 체험하기",
        "오늘의 개인 최고 점수 하나 만들어보기",
        "새로운 규칙이나 이용법 하나 배워보기",
        "가장 재미있었던 순간 하나 기억해보기",
    ),
    "shopping": (
        "예산 안에서 가장 마음에 드는 물건 하나 골라보기",
        "처음 보는 브랜드 하나 구경하기",
        "사고 싶지만 오늘은 사지 않을 물건 하나 골라보기",
        "선물하고 싶은 물건 하나 찾아보기",
        "평소 보지 않던 코너 한 곳 둘러보기",
    ),
    "drink": (
        "평소 안 먹던 안주 하나 골라보기",
        "메뉴판에서 처음 보는 메뉴 하나 찾아보기",
        "오늘 분위기에 어울리는 안주 하나 고르기",
        "천천히 대화하며 첫 잔 즐기기",
        "과음하지 않고 가장 맛있었던 메뉴 하나 고르기",
    ),
}


class NoAdventureCandidateError(Exception):
    """실제 방문 가능한 서울 가챠 후보가 없음."""


def recommend_random_quest(activity: str, *, choice_fn=choice):
    return {
        "activity": activity,
        "quest": choice_fn(RANDOM_QUESTS[activity]),
    }


# 서울 가챠는 지정 지역을 우선하고, 없으면 추천 후보군 안에서 무작위로 한 지역을 선택한다.
def recommend_seoul_gacha(
    request: SeoulGachaRequest,
    *,
    choice_fn=choice,
):
    if request.target_area is not None:
        selected_area = request.target_area
        selection_source = "target"
    else:
        seen = set()
        recommended_pool = []
        for area in [request.current_area, *request.other_areas]:
            if area is None:
                continue
            key = (area.AREA_NM, area.latitude, area.longitude)
            if key not in seen:
                seen.add(key)
                recommended_pool.append(area)

        if recommended_pool:
            selected_area = choice_fn(recommended_pool)
            selection_source = "recommended"
        elif request.extended_areas:
            selected_area = choice_fn(request.extended_areas)
            selection_source = "extended"
        else:
            raise NoAdventureCandidateError

    context = request.recommendation_context
    place_request = PlaceRecommendRequest(
        area_name=selected_area.AREA_NM,
        latitude=selected_area.latitude,
        longitude=selected_area.longitude,
        activities=context.activities,
        space_preference=context.space_preference,
        activity_preferences=context.activity_preferences,
    )
    return {
        "selected_area": selected_area,
        "selection_source": selection_source,
        "place_request": place_request,
        "recommendation_context": context,
    }


def recommend_single_place_gacha(
    request: AdventureRequest,
    *,
    recommend_places_fn=recommend_places,
    validate_stay_time_fn=validate_selected_places_stay_time,
    calculate_course_fn=calculate_course,
    optimize_course_order_fn=optimize_course_order,
    choice_fn=choice,
):
    area = request.area
    context = request.recommendation_context
    ranked_places = recommend_places_fn(
        area_name=area.area_name,
        latitude=area.latitude,
        longitude=area.longitude,
        activities=context.activities,
        companions=[],
        budget_max=None,
        budget_preference=None,
        space_preference=context.space_preference,
        activity_preferences=context.activity_preferences,
    )
    
    # 단일 장소 가챠도 랜덤 선택 전에 체류시간·실제 경로·영업 가능 여부를 먼저 검증한다.
    open_candidates = []
    unknown_candidates = []

    for place in ranked_places[:MAX_GACHA_VALIDATION_CANDIDATES]:
        stay_validation = validate_stay_time_fn(
            [{
                "activity": place["category"],
                "specified_duration_minutes": place.get(
                    "specified_duration_minutes"
                ),
            }],
            context.available_time_minutes,
        )
        if stay_validation["status"] == IMPOSSIBLE_BY_STAY_TIME:
            continue

        course_request = CourseCalculationRequest(
            start_location=context.start_location,
            selected_places=[place.copy()],
            available_time_minutes=context.available_time_minutes,
            departure_datetime=context.departure_datetime,
            end_location=context.end_location,
            transport_mode=context.transport_mode,
        )

        try:
            course_result = calculate_course_fn(
                course_request,
                optimize_course_order_fn,
            )
        except HTTPException as error:
            if error.status_code == 502:
                continue
            raise

        if course_result["status"] != "FEASIBLE":
            continue

        course_place = course_result["optimized_places"][0]
        availability = course_place["availability"]
        availability_status = availability["status"]
        if availability_status not in {"open", "unknown"}:
            continue

        candidate = {
            "place": {
                key: value
                for key, value in course_place.items()
                if key != "availability"
            },
            "availability": availability,
            "availability_confirmed": availability_status == "open",
            "course_preview": {
                key: course_result[key]
                for key in (
                    "status",
                    "total_travel_time_minutes",
                    "total_stay_time_minutes",
                    "total_required_minutes",
                    "remaining_time_minutes",
                )
            },
            "course_request": course_request.model_dump(),
        }

        if availability_status == "open":
            open_candidates.append(candidate)
        else:
            unknown_candidates.append(candidate)

    # 영업 확인 후보를 우선하고, 확인 불가(unknown)는 방문 불가로 단정하지 않고 fallback으로 사용한다.
    candidates = open_candidates or unknown_candidates
    if not candidates:
        raise NoAdventureCandidateError

    return choice_fn(candidates)


def create_blind_single_place_gacha(
    request: AdventureRequest,
    *,
    recommend_single_fn=recommend_single_place_gacha,
    store_fn=store_blind_adventure,
):
    result = AdventureResponse.model_validate(recommend_single_fn(request))
    token = store_fn(result.model_dump())
    return {
        "token": token,
        "category": result.place["category"],
        "availability_confirmed": result.availability_confirmed,
        "expires_in_seconds": BLIND_ADVENTURE_TTL_SECONDS,
    }


def reveal_blind_single_place_gacha(
    token: str,
    *,
    get_fn=get_blind_adventure,
):
    return get_fn(token)


def create_blind_two_place_gacha(
    request: AdventureRequest,
    *,
    recommend_course_fn=None,
    store_fn=store_blind_adventure,
):
    recommend_course_fn = recommend_course_fn or recommend_two_place_gacha
    result = AdventureCourseResponse.model_validate(recommend_course_fn(request))
    token = store_fn(result.model_dump(), kind="course")
    return {
        "token": token,
        "place_count": 2,
        "activities": [place["category"] for place in result.places],
        "availability_confirmed": result.availability_confirmed,
        "expires_in_seconds": BLIND_ADVENTURE_TTL_SECONDS,
    }


def reveal_blind_two_place_gacha(
    token: str,
    *,
    get_fn=get_blind_adventure,
):
    return get_fn(token, kind="course")


def _is_same_place(first: dict, second: dict) -> bool:
    if first.get("source_id") is not None and second.get("source_id") is not None:
        return (
            first.get("source"),
            first["source_id"],
        ) == (
            second.get("source"),
            second["source_id"],
        )

    return (
        first.get("name"),
        first.get("latitude"),
        first.get("longitude"),
    ) == (
        second.get("name"),
        second.get("latitude"),
        second.get("longitude"),
    )

def _distance_between_places_m(first: dict, second: dict) -> float:
    from math import radians, sin, cos, sqrt, atan2

    lat1 = radians(first["latitude"])
    lon1 = radians(first["longitude"])
    lat2 = radians(second["latitude"])
    lon2 = radians(second["longitude"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return 6371000 * c

# 2장소 가챠는 동일 장소와 지나치게 가까운 조합을 제외한 뒤 검증 가능한 조합 수만 남긴다.
def _course_gacha_combinations(places: list[dict], prefer_diverse: bool):
    pairs = [
        pair
        for pair in combinations(
            places[:MAX_COURSE_GACHA_PLACE_CANDIDATES],
            2,
        )
        if not _is_same_place(*pair)
        and _distance_between_places_m(*pair) >= MIN_COURSE_GACHA_PLACE_DISTANCE_M
    ]
    if not prefer_diverse:
        return [(pair, False) for pair in pairs][
            :MAX_COURSE_GACHA_VALIDATION_COMBINATIONS
        ]

    diverse = [pair for pair in pairs if pair[0]["category"] != pair[1]["category"]]
    same = [pair for pair in pairs if pair[0]["category"] == pair[1]["category"]]

    if not diverse:
        return [(pair, False) for pair in same][
            :MAX_COURSE_GACHA_VALIDATION_COMBINATIONS
        ]
    if not same:
        return [(pair, True) for pair in diverse][
            :MAX_COURSE_GACHA_VALIDATION_COMBINATIONS
        ]

    # 다양한 activity가 모두 실패해도 검증 상한 안에서 같은 activity를
    # 한 번 확인할 수 있도록 마지막 한 자리를 fallback에 남긴다.
    planned = [(pair, True) for pair in diverse[:2]]
    planned.append((same[0], False))
    return planned[:MAX_COURSE_GACHA_VALIDATION_COMBINATIONS]


def recommend_two_place_gacha(
    request: AdventureRequest,
    *,
    recommend_places_fn=recommend_places,
    validate_stay_time_fn=validate_selected_places_stay_time,
    calculate_course_fn=calculate_course,
    optimize_course_order_fn=optimize_course_order,
    choice_fn=choice,
):
    area = request.area
    context = request.recommendation_context
    ranked_places = recommend_places_fn(
        area_name=area.area_name,
        latitude=area.latitude,
        longitude=area.longitude,
        activities=context.activities,
        companions=[],
        budget_max=None,
        budget_preference=None,
        space_preference=context.space_preference,
        activity_preferences=context.activity_preferences,
    )

    if not ranked_places:
        raise NoAdventureCandidateError

    planned_pairs = _course_gacha_combinations(
        ranked_places,
        prefer_diverse=len(context.activities) > 1,
    )
    # 활동 다양성과 실제 영업 확인 개수를 기준으로 후보 pool을 나눠 최종 랜덤 선택의 우선순위를 유지한다.
    pools = {
        True: {2: [], 1: [], 0: []},
        False: {2: [], 1: [], 0: []},
    }

    for pair, is_diverse in planned_pairs:
        stay_validation = validate_stay_time_fn(
            [
                {
                    "activity": place["category"],
                    "specified_duration_minutes": place.get(
                        "specified_duration_minutes"
                    ),
                }
                for place in pair
            ],
            context.available_time_minutes,
        )
        if stay_validation["status"] == IMPOSSIBLE_BY_STAY_TIME:
            continue

        course_request = CourseCalculationRequest(
            start_location=context.start_location,
            selected_places=[place.copy() for place in pair],
            available_time_minutes=context.available_time_minutes,
            departure_datetime=context.departure_datetime,
            end_location=context.end_location,
            transport_mode=context.transport_mode,
        )
        try:
            course_result = calculate_course_fn(
                course_request,
                optimize_course_order_fn,
            )
        except HTTPException as error:
            if error.status_code == 502:
                continue
            raise

        if course_result["status"] != "FEASIBLE":
            continue

        optimized_places = course_result["optimized_places"]
        availabilities = [place["availability"] for place in optimized_places]
        statuses = [availability["status"] for availability in availabilities]
        if any(status not in {"open", "unknown"} for status in statuses):
            continue

        open_count = statuses.count("open")
        pools[is_diverse][open_count].append({
            "places": [
                {
                    key: value
                    for key, value in place.items()
                    if key != "availability"
                }
                for place in optimized_places
            ],
            "availabilities": availabilities,
            "availability_confirmed": open_count == 2,
            "course_preview": {
                key: course_result[key]
                for key in (
                    "status",
                    "total_travel_time_minutes",
                    "total_stay_time_minutes",
                    "total_required_minutes",
                    "remaining_time_minutes",
                )
            },
            "course_request": course_request.model_dump(),
        })

    activity_groups = (
        (True, False)
        if len(context.activities) > 1
        else (False, True)
    )
    for is_diverse in activity_groups:
        for open_count in (2, 1, 0):
            candidates = pools[is_diverse][open_count]
            if candidates:
                return choice_fn(candidates)

    raise NoAdventureCandidateError
