from itertools import permutations

from course_time_evaluator import evaluate_course_time


MAX_OPTIMIZATION_PLACES = 6


def optimize_course_order(
    start_location: dict,
    selected_places: list[dict],
    available_time_minutes: int,
    end_location: dict | None = None,
    transport_mode: str = "auto",
) -> dict:
    if len(selected_places) > MAX_OPTIMIZATION_PLACES:
        raise ValueError(
            f"방문 순서 최적화는 최대 {MAX_OPTIMIZATION_PLACES}개 장소까지 지원합니다."
        )

    preferred_places = [
        place
        for place in selected_places
        if place.get("preferred_first", False)
    ]
    if len(preferred_places) > 1:
        raise ValueError(
            "preferred_first=True인 장소는 최대 1개만 허용됩니다."
        )

    if preferred_places:
        preferred_place = preferred_places[0]
        remaining_places = [
            place
            for place in selected_places
            if place is not preferred_place
        ]
        orders = (
            (preferred_place, *remaining_order)
            for remaining_order in permutations(remaining_places)
        )
    else:
        orders = (
            [tuple(selected_places)]
            if len(selected_places) <= 1
            else permutations(selected_places)
        )
    travel_cache = {}
    best_order = None
    best_result = None

    for order in orders:
        try:
            result = evaluate_course_time(
                start_location,
                list(order),
                available_time_minutes,
                end_location,
                transport_mode,
                travel_cache,
            )
        except RuntimeError:
            continue

        if (
            best_result is None
            or result["total_travel_time_minutes"]
            < best_result["total_travel_time_minutes"]
        ):
            best_order = list(order)
            best_result = result

    if best_result is None:
        raise RuntimeError(
            "모든 방문 순서의 이동시간을 계산할 수 없습니다."
        )

    return {
        "optimized_places": best_order,
        **best_result,
    }
