from datetime import date, datetime
from activity_duration_policy import get_activity_duration_policy
from candidate_filter import calculate_available_stay_minutes
from map_service import get_travel
from place_availability import SEOUL_TIMEZONE, evaluate_place_availability
from popup_service import load_current_popup_places as load_popup_places
from seoul_culture_service import (
    calculate_distance_m,
    get_nearby_current_seoul_culture_places,
)


MAX_DISTANCE_M = 2000
MAX_TRAVEL_CANDIDATES = 3
MAX_DETOUR_TRAVEL_MINUTES = 15
ENDING_SOON_DAYS = 3


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _duration_minutes(travel):
    if not isinstance(travel, dict):
        return None

    duration = travel.get("duration_min")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return None
    return duration if duration >= 0 else None


def _message(
    place,
    days_left,
    travel_mode,
    travel_minutes,
    visitable_minutes,
    departure_datetime,
    suggestion_type,
):
    name = place["name"]
    now = datetime.now(SEOUL_TIMEZONE)
    future_departure = departure_datetime > now
    departure_time = departure_datetime.strftime("%H시 %M분")
    mode_text = {
        "walk": "도보로",
        "transit": "대중교통으로",
        "car": "차량으로",
    }.get(travel_mode)
    travel_text = (
        f"{mode_text} 약 {travel_minutes}분"
        if mode_text
        else f"약 {travel_minutes}분"
    )

    if days_left == 0:
        ending_text = "오늘이 마지막 날이에요."
    else:
        ending_text = f"{days_left}일 뒤 종료돼요."

    if future_departure:
        visit_text = (
            f"{departure_time}에 출발하면 {travel_text}이고, "
            f"도착 후 약 {visitable_minutes}분 둘러볼 수 있어요."
        )
    else:
        visit_text = (
            f"현재 위치에서 {travel_text}이고, "
            f"{'지금 출발하면' if days_left == 0 else '지금 방문하면'} "
            f"약 {visitable_minutes}분 둘러볼 수 있어요."
        )

    if suggestion_type == "detour":
        return (
            f"오늘이 마지막 날인 '{name}'도 다른 선택지로 제안드려요. "
            f"{visit_text} 확인해 보실래요?"
        )

    return f"'{name}', {ending_text} {visit_text} 확인해 보실래요?"


def find_proactive_suggestion(
    start_location,
    departure_datetime,
    end_location,
    end_datetime,
    transport_mode,
    activities=None,
    *,
    load_popup_places_fn=load_popup_places,
    load_culture_places_fn=get_nearby_current_seoul_culture_places,
    get_travel_fn=get_travel,
    evaluate_availability_fn=evaluate_place_availability,
):
    """종료가 임박했고 실제로 방문 가능한 팝업·문화행사 한 곳을 찾는다."""

    latitude = float(start_location["y"])
    longitude = float(start_location["x"])
    departure_datetime = departure_datetime.astimezone(SEOUL_TIMEZONE)
    departure_date = departure_datetime.date()
    requested_activities = set(activities or [])
    candidates = []

    try:
        popup_places = load_popup_places_fn()
    except Exception:
        popup_places = []

    try:
        culture_places = load_culture_places_fn(
            latitude=latitude,
            longitude=longitude,
            max_distance_m=MAX_DISTANCE_M,
            reference_date=departure_date,
        )
    except Exception:
        culture_places = []

    for place in [*popup_places, *culture_places]:
        start_at = _parse_date(place.get("start_at"))
        end_at = _parse_date(place.get("end_at"))
        if (
            end_at is None
            or departure_date > end_at
            or (start_at is not None and departure_date < start_at)
            or place.get("operation_schedule_status") != "parsed"
        ):
            continue

        days_left = (end_at - departure_date).days
        if not 0 <= days_left <= ENDING_SOON_DAYS:
            continue

        activity_matches = (
            not requested_activities
            or place.get("category") in requested_activities
        )
        if not activity_matches and days_left > 0:
            continue

        suggestion_type = "timely" if activity_matches else "detour"
        priority = (
            0
            if not requested_activities or activity_matches and days_left == 0
            else 1
            if suggestion_type == "detour"
            else 2
        )

        try:
            distance_m = calculate_distance_m(
                latitude,
                longitude,
                place["latitude"],
                place["longitude"],
            )
        except (KeyError, TypeError, ValueError):
            continue

        if distance_m <= MAX_DISTANCE_M:
            candidates.append(
                (priority, days_left, distance_m, suggestion_type, place)
            )

    candidates.sort(key=lambda item: item[:3])

    for _, days_left, _, suggestion_type, place in candidates[
        :MAX_TRAVEL_CANDIDATES
    ]:
        try:
            travel = get_travel_fn(
                longitude,
                latitude,
                place["longitude"],
                place["latitude"],
                transport_mode=transport_mode,
            )
            travel_minutes = _duration_minutes(travel)
            if travel_minutes is None:
                continue
            if (
                suggestion_type == "detour"
                and travel_minutes > MAX_DETOUR_TRAVEL_MINUTES
            ):
                continue

            availability = evaluate_availability_fn(
                place,
                departure_datetime,
                travel_minutes,
            )
            if availability.get("status") != "open":
                continue

            minimum_stay = get_activity_duration_policy(
                place["category"]
            )["min"]
            remaining_minutes = availability.get("remaining_minutes")
            if remaining_minutes is None or remaining_minutes < minimum_stay:
                continue

            fits_before_next_schedule = None
            visitable_minutes = remaining_minutes

            if end_datetime is not None:
                onward_minutes = 0

                if end_location is not None:
                    onward = get_travel_fn(
                        place["longitude"],
                        place["latitude"],
                        end_location["x"],
                        end_location["y"],
                        transport_mode=transport_mode,
                    )
                    onward_minutes = _duration_minutes(onward)
                    if onward_minutes is None:
                        continue

                time_window_minutes = int(
                    (end_datetime - departure_datetime).total_seconds() / 60
                )
                schedule_minutes = calculate_available_stay_minutes(
                    time_window_minutes,
                    travel_minutes,
                    onward_minutes,
                )
                if schedule_minutes < minimum_stay:
                    continue

                if end_location is not None:
                    fits_before_next_schedule = True

                visitable_minutes = min(remaining_minutes, schedule_minutes)

            return {
                "suggestion_type": suggestion_type,
                "place": {
                    key: place.get(key)
                    for key in (
                        "source",
                        "source_id",
                        "name",
                        "latitude",
                        "longitude",
                        "category",
                        "start_at",
                        "end_at",
                        "image_url",
                        "detail_url",
                        "official_url",
                        "operation_schedule",
                        "operation_schedule_status",
                    )
                },
                "reason": "ending_today" if days_left == 0 else "ending_soon",
                "travel": {
                    "mode": travel.get("mode"),
                    "duration_min": travel_minutes,
                },
                "availability": availability,
                "visitable_minutes": visitable_minutes,
                "fits_before_next_schedule": fits_before_next_schedule,
                "message": _message(
                    place,
                    days_left,
                    travel.get("mode"),
                    travel_minutes,
                    visitable_minutes,
                    departure_datetime,
                    suggestion_type,
                ),
            }
        except (KeyError, TypeError, ValueError):
            continue

    return None
