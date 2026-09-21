from route_leg_builder import build_travel_legs
from route_travel_time import calculate_route_travel_times
from stay_time_validation import validate_selected_places_stay_time


FEASIBLE = "FEASIBLE"
INFEASIBLE = "INFEASIBLE"


def evaluate_course_time(
    start_location: dict,
    selected_places: list[dict],
    available_time_minutes: int,
    end_location: dict | None = None,
    transport_mode: str = "auto",
    travel_cache: dict | None = None,
) -> dict:
    # 체류시간 사전검증과 실제 directed leg 이동시간을 같은 선택 순서에 대해 합산한다.
    stay_time_result = validate_selected_places_stay_time(
        selected_places,
        available_time_minutes,
    )
    legs = build_travel_legs(
        start_location,
        selected_places,
        end_location,
    )
    # 단독 course 계산은 cache 없이도 동작하고, 순서 최적화는 공유 cache를 전달해 중복 조회를 줄인다.
    if travel_cache is None:
        travel_time_result = calculate_route_travel_times(
            legs,
            transport_mode,
        )
    else:
        travel_time_result = calculate_route_travel_times(
            legs,
            transport_mode,
            travel_cache,
        )

    total_stay_time_minutes = stay_time_result["total_stay_duration_minutes"]
    total_travel_time_minutes = travel_time_result["total_travel_time_minutes"]
    total_required_minutes = (
        total_stay_time_minutes + total_travel_time_minutes
    )
    remaining_time_minutes = available_time_minutes - total_required_minutes

    # 남은 시간이 음수면 장소·이동시간 세부값은 보존하되 코스 상태만 INFEASIBLE로 표시한다.
    return {
        "legs": travel_time_result["legs"],
        "total_stay_time_minutes": total_stay_time_minutes,
        "total_travel_time_minutes": total_travel_time_minutes,
        "total_required_minutes": total_required_minutes,
        "available_time_minutes": available_time_minutes,
        "remaining_time_minutes": remaining_time_minutes,
        "status": FEASIBLE if remaining_time_minutes >= 0 else INFEASIBLE,
    }
