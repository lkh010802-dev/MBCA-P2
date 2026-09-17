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
    stay_time_result = validate_selected_places_stay_time(
        selected_places,
        available_time_minutes,
    )
    legs = build_travel_legs(
        start_location,
        selected_places,
        end_location,
    )
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

    return {
        "legs": travel_time_result["legs"],
        "total_stay_time_minutes": total_stay_time_minutes,
        "total_travel_time_minutes": total_travel_time_minutes,
        "total_required_minutes": total_required_minutes,
        "available_time_minutes": available_time_minutes,
        "remaining_time_minutes": remaining_time_minutes,
        "status": FEASIBLE if remaining_time_minutes >= 0 else INFEASIBLE,
    }
