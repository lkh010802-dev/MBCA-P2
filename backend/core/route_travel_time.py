from map_service import get_travel


def calculate_route_travel_times(
    legs: list[dict],
    transport_mode: str = "auto",
    travel_cache: dict | None = None,
) -> dict:
    legs_with_travel_time = []
    total_travel_time_minutes = 0

    for index, leg in enumerate(legs):
        origin = leg["origin"]
        destination = leg["destination"]
        cache_key = (
            origin["longitude"],
            origin["latitude"],
            destination["longitude"],
            destination["latitude"],
            transport_mode,
        )
        if travel_cache is not None and cache_key in travel_cache:
            travel = travel_cache[cache_key]
        else:
            travel = get_travel(
                *cache_key[:4],
                transport_mode=transport_mode,
            )
            if travel_cache is not None:
                travel_cache[cache_key] = travel

        if travel is None or "duration_min" not in travel:
            raise RuntimeError(
                f"이동시간을 계산할 수 없는 구간입니다: leg_index={index}"
            )

        duration_minutes = travel["duration_min"]
        legs_with_travel_time.append(
            {**leg, "travel_time_minutes": duration_minutes}
        )
        total_travel_time_minutes += duration_minutes

    return {
        "legs": legs_with_travel_time,
        "total_travel_time_minutes": total_travel_time_minutes,
    }
