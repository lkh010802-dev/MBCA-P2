from datetime import timedelta
import logging

from fastapi import APIRouter, HTTPException

from activity_duration_policy import determine_stay_duration
from course_order_optimizer import optimize_course_order
from course_time_evaluator import evaluate_course_time
from models import CourseCalculationRequest
from place_availability import evaluate_place_availability
from audit_trace import record

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


def calculate_course(
    request: CourseCalculationRequest,
    optimize_course_order_fn,
):
    selected_places = []
    for place in request.selected_places:
        place_data = place.model_dump()
        place_data["activity"] = place_data["category"]
        selected_places.append(place_data)

    try:
        end_location = (
            request.end_location.model_dump()
            if request.end_location is not None
            else None
        )
        if request.optimize_order:
            course_result = optimize_course_order_fn(
                start_location=request.start_location.model_dump(),
                selected_places=selected_places,
                available_time_minutes=request.available_time_minutes,
                end_location=end_location,
                transport_mode=request.transport_mode,
            )
        else:
            course_result = {
                "optimized_places": selected_places,
                **evaluate_course_time(
                    request.start_location.model_dump(),
                    selected_places,
                    request.available_time_minutes,
                    end_location,
                    request.transport_mode,
                ),
            }

        if request.departure_datetime is not None:
            cursor = request.departure_datetime
            places_with_availability = []

            for index, place in enumerate(course_result["optimized_places"]):
                travel_minutes = course_result["legs"][index][
                    "travel_time_minutes"
                ]
                availability = evaluate_place_availability(
                    place,
                    cursor,
                    travel_minutes,
                )
                places_with_availability.append({
                    **place,
                    "availability": availability,
                })
                cursor = availability["arrival_at"] + timedelta(
                    minutes=determine_stay_duration(
                        place["activity"],
                        place.get("specified_duration_minutes"),
                    )
                )

            course_result["optimized_places"] = places_with_availability

        cleaned_optimized_places = []

        for place in course_result["optimized_places"]:
            cleaned_place = place.copy()
            cleaned_place['stay_duration_minutes'] = determine_stay_duration(place['category'], place.get('specified_duration_minutes'))
            cleaned_place.pop("activity", None)
            cleaned_place.pop("preferred_first", None)
            cleaned_optimized_places.append(cleaned_place)

        course_result["optimized_places"] = cleaned_optimized_places

        expected_total = course_result["total_travel_time_minutes"] + course_result["total_stay_time_minutes"]
        expected_remaining = request.available_time_minutes - expected_total
        warnings = []
        if course_result["total_required_minutes"] != expected_total:
            warnings.append("total_mismatch")
        if course_result["remaining_time_minutes"] != expected_remaining:
            warnings.append("remaining_mismatch")
        if course_result["status"] != (
            "FEASIBLE" if expected_remaining >= 0 else "INFEASIBLE"
        ):
            warnings.append("status_mismatch")
        record("course_result", transport_mode=request.transport_mode,
               selected_place_ids=[place.get("source_id") or place.get("name") for place in cleaned_optimized_places],
               course_result=course_result, warnings=warnings)
        if warnings:
            raise RuntimeError(f"코스 계산 계약이 일치하지 않습니다: {', '.join(warnings)}")

        return course_result

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except RuntimeError as error:
        logger.error("[course-route-error] %s", error)
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error


@router.post("/recommend/course")
def calculate_course_endpoint(
    request: CourseCalculationRequest,
):
    return calculate_course(request, optimize_course_order)
