from itertools import permutations

from activity_duration_policy import (
    determine_stay_duration,
    get_activity_duration_policy,
)

from candidate_filter import calculate_straight_distance_km

IMPOSSIBLE_BY_STAY_TIME = "IMPOSSIBLE_BY_STAY_TIME"
TIGHT_BY_STAY_TIME = "TIGHT_BY_STAY_TIME"
PENDING_TRAVEL_TIME_VALIDATION = "PENDING_TRAVEL_TIME_VALIDATION"
SELECTION_WALK_THRESHOLD_KM = 1.0


def validate_selected_places_stay_time(
    selected_places: list[dict],
    available_time_minutes: int,
) -> dict:
    stay_durations_minutes = []
    minimum_stay_durations_minutes = []

    for place in selected_places:
        specified_duration_minutes = place.get("specified_duration_minutes")
        stay_durations_minutes.append(
            determine_stay_duration(
                place["activity"],
                specified_duration_minutes,
            )
        )
        minimum_stay_durations_minutes.append(
            specified_duration_minutes
            if specified_duration_minutes is not None
            else get_activity_duration_policy(place["activity"])["min"]
        )

    total_stay_duration_minutes = sum(stay_durations_minutes)
    total_minimum_stay_duration_minutes = sum(
        minimum_stay_durations_minutes
    )

    if total_minimum_stay_duration_minutes > available_time_minutes:
        status = IMPOSSIBLE_BY_STAY_TIME
    elif total_stay_duration_minutes > available_time_minutes:
        status = TIGHT_BY_STAY_TIME
    else:
        status = PENDING_TRAVEL_TIME_VALIDATION

    return {
        "status": status,
        "stay_durations_minutes": stay_durations_minutes,
        "minimum_stay_durations_minutes": minimum_stay_durations_minutes,
        "total_stay_duration_minutes": total_stay_duration_minutes,
        "total_minimum_stay_duration_minutes": (
            total_minimum_stay_duration_minutes
        ),
    }

def estimate_transit_minutes_by_distance(
    distance_km: float,
) -> int:
    """
    선택 단계에서 외부 이동 API를 호출하지 않고
    대중교통 이동시간을 대략적으로 추정한다.

    서울 대중교통 O/D 표본을 참고한
    KOALA MVP용 거리 구간별 휴리스틱이다.

    최종 이동 가능 여부는 이 값으로 확정하지 않고,
    /recommend/course의 실제 이동시간으로 다시 검증한다.
    """

    if distance_km <= 3:
        return 12

    if distance_km <= 5:
        return 18

    if distance_km <= 8:
        return 24

    if distance_km <= 12:
        return 35

    if distance_km <= 16:
        return 40

    return 50


def estimate_travel_minutes_by_distance(
    distance_km: float,
) -> int:
    """
    선택 단계에서 직선거리를 기준으로
    대략적인 이동시간을 계산한다.

    - 1.0km 이하: 도보 이동으로 추정
    - 1.0km 초과: 대중교통 이동으로 추정

    대중교통 예상시간은
    서울 대중교통 O/D 표본을 참고한
    MVP 거리 구간별 값을 사용한다.

    외부 이동 API는 호출하지 않는다.
    최종 이동시간은 /recommend/course에서 다시 계산한다.
    """

    # 1km 이하는 도보로 이동한다고 가정한다.
    if distance_km <= SELECTION_WALK_THRESHOLD_KM:
        walking_distance_km = distance_km * 1.2

        walking_minutes = (
            walking_distance_km / 4.5
        ) * 60

        return round(walking_minutes)

    # 1km 초과는 서울 대중교통 O/D 표본을 참고한
    # MVP 거리 구간별 예상시간을 사용한다.
    return estimate_transit_minutes_by_distance(
        distance_km
    )

def calculate_estimated_route_travel_minutes(
    start_latitude: float,
    start_longitude: float,
    selected_places: list[dict],
) -> dict:
    """
    선택한 장소들의 위도·경도를 이용해
    외부 이동 API 호출 없이 대략적인 이동시간을 계산한다.

    사용자가 장소를 선택한 순서가 아니라,
    가능한 방문 순서를 비교해서 예상 이동시간이
    가장 짧은 순서를 사용한다.

    이 결과는 선택 단계의 사전검증용이며,
    최종 이동시간은 /recommend/course에서 다시 계산한다.
    """

    best_order = None
    best_travel_minutes = None

    for order in permutations(selected_places):

        total_travel_minutes = 0

        current_latitude = start_latitude
        current_longitude = start_longitude

        for place in order:

            distance_km = calculate_straight_distance_km(
                current_latitude,
                current_longitude,
                place["latitude"],
                place["longitude"],
            )

            total_travel_minutes += (
                estimate_travel_minutes_by_distance(
                    distance_km
                )
            )

            current_latitude = place["latitude"]
            current_longitude = place["longitude"]

        if (
            best_travel_minutes is None
            or total_travel_minutes < best_travel_minutes
        ):
            best_travel_minutes = total_travel_minutes
            best_order = list(order)

    return {
        "estimated_travel_minutes": best_travel_minutes,
        "estimated_order": best_order,
    }
