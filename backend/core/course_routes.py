from datetime import timedelta

from fastapi import APIRouter, HTTPException

from activity_duration_policy import determine_stay_duration
from course_order_optimizer import optimize_course_order
from models import CourseCalculationRequest
from place_availability import evaluate_place_availability


router = APIRouter()


def calculate_course(
    request: CourseCalculationRequest,
    optimize_course_order_fn,
):
    # 코스 최적화 내부 규격에 맞추기 위해 장소 category를 activity 필드로 변환한다.
    selected_places = []
    for place in request.selected_places:
        place_data = place.model_dump()
        place_data["activity"] = place_data["category"]
        selected_places.append(place_data)

    try:
        course_result = optimize_course_order_fn(
            start_location=request.start_location.model_dump(),
            selected_places=selected_places,
            available_time_minutes=request.available_time_minutes,
            end_location=(
                request.end_location.model_dump()
                if request.end_location is not None
                else None
            ),
            transport_mode=request.transport_mode,
        )

        # 출발 시각이 있으면 최적 방문 순서대로 도착 시각과 영업 가능 여부를 계산한다.
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

        # 내부 계산에만 사용한 보조 필드는 최종 API 응답에서 제거한다.
        cleaned_optimized_places = []

        for place in course_result["optimized_places"]:
            cleaned_place = place.copy()
            cleaned_place.pop("activity", None)
            cleaned_place.pop("preferred_first", None)
            cleaned_optimized_places.append(cleaned_place)

        course_result["optimized_places"] = cleaned_optimized_places

        return course_result

    # 입력 조건상 코스를 구성할 수 없는 경우는 클라이언트 요청 오류로 반환한다.
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    # 실제 이동시간 계산 등 실행 단계 실패는 외부 연동 오류로 구분한다.
    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error


@router.post("/recommend/course")
def calculate_course_endpoint(
    request: CourseCalculationRequest,
):
    return calculate_course(request, optimize_course_order)
