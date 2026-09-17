from math import isfinite
from numbers import Real

from map_service import get_travel


def _same_location(origin: dict, destination: dict) -> bool:
    return (
        abs(float(origin["latitude"]) - float(destination["latitude"])) < 1e-7
        and abs(float(origin["longitude"]) - float(destination["longitude"])) < 1e-7
    )


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
        if (
            isinstance(duration_minutes, bool)
            or not isinstance(duration_minutes, Real)
            or not isfinite(float(duration_minutes))
            or duration_minutes < 0
            or (duration_minutes == 0 and not _same_location(origin, destination))
        ):
            raise RuntimeError(
                f"유효한 이동시간을 계산할 수 없는 구간입니다: leg_index={index}"
            )
        travel = {
            **travel,
            "route_status": "complete" if any(
                isinstance(segment, dict)
                and isinstance(segment.get("points"), list)
                and len(segment["points"]) >= 2
                for segment in (travel.get("paths") or [])
            ) else "estimated",
        }
        legs_with_travel_time.append(
            {**leg, "travel_time_minutes": duration_minutes, "travel": travel}
        )
        total_travel_time_minutes += duration_minutes

    return {
        "legs": legs_with_travel_time,
        "total_travel_time_minutes": total_travel_time_minutes,
    }
