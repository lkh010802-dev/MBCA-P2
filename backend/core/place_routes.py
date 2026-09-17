from fastapi import APIRouter, HTTPException

from models import (
    PlaceRecommendMoreRequest,
    PlaceRecommendRequest,
    PlaceSelectionValidationRequest,
)
from place_recommendation_cache import (
    PlaceCursorExpiredError,
    PlaceCursorNotFoundError,
    create_place_recommendation_page,
    get_next_place_recommendation_page,
)
from place_recommendation_service import recommend_places
from stay_time_validation import (
    calculate_estimated_route_travel_minutes,
    validate_selected_places_stay_time,
)


router = APIRouter()


def recommend_actual_places(
    request: PlaceRecommendRequest,
    recommend_places_fn,
    create_page_fn,
):
    ranked_places = recommend_places_fn(
        area_name=request.area_name,
        latitude=request.latitude,
        longitude=request.longitude,
        activities=request.activities,
        companions=request.companions,
        budget_max=request.budget_max,
        budget_preference=request.budget_preference,
        space_preference=request.space_preference,
        activity_preferences=request.activity_preferences,
    )

    page = create_page_fn(
        area_name=request.area_name,
        places=ranked_places,
    )

    return {
        "area_name": page.area_name,
        "places": page.places,
        "cursor": page.cursor,
        "has_more": page.has_more,
        "next_offset": page.next_offset,
    }


def recommend_more_actual_places(
    request: PlaceRecommendMoreRequest,
    get_next_page_fn,
):
    try:
        page = get_next_page_fn(
            request.cursor,
            request.offset,
        )

    except PlaceCursorExpiredError as error:
        raise HTTPException(
            status_code=410,
            detail="장소 추천 cursor가 만료되었습니다.",
        ) from error

    except PlaceCursorNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail="유효하지 않은 장소 추천 cursor입니다.",
        ) from error

    return {
        "area_name": page.area_name,
        "places": page.places,
        "cursor": page.cursor,
        "has_more": page.has_more,
        "next_offset": page.next_offset,
    }


@router.post("/recommend/places")
def recommend_actual_places_endpoint(
    request: PlaceRecommendRequest,
):
    return recommend_actual_places(
        request,
        recommend_places,
        create_place_recommendation_page,
    )


@router.post("/recommend/places/more")
def recommend_more_actual_places_endpoint(
    request: PlaceRecommendMoreRequest,
):
    return recommend_more_actual_places(
        request,
        get_next_place_recommendation_page,
    )


def validate_place_selection(
    request: PlaceSelectionValidationRequest,
    validate_stay_time_fn,
    calculate_estimated_travel_fn,
):
    selected_places = [
        place.model_dump()
        for place in request.selected_places
    ]
    validation_result = validate_stay_time_fn(
        [
            {
                "activity": place["category"],
                "specified_duration_minutes": place.get(
                    "specified_duration_minutes"
                ),
            }
            for place in selected_places
        ],
        request.available_time_minutes,
    )
    estimated_travel_result = calculate_estimated_travel_fn(
        start_latitude=request.start_latitude,
        start_longitude=request.start_longitude,
        selected_places=selected_places,
    )

    estimated_travel_minutes = estimated_travel_result[
        "estimated_travel_minutes"
    ]

    estimated_total_required_minutes = (
        validation_result["total_stay_duration_minutes"]
        + estimated_travel_minutes
    )

    estimated_minimum_required_minutes = (
        validation_result["total_minimum_stay_duration_minutes"]
        + estimated_travel_minutes
    )
    # 예상 이동시간까지 포함했을 때
    # 현재 선택이 시간상 빡빡할 가능성이 있는지 확인한다.
    travel_time_warning = (
        estimated_minimum_required_minutes
        > request.available_time_minutes
    )
    return {
        "status": validation_result["status"],
        "selected_places": selected_places,

        "stay_time_validation": {
            key: value
            for key, value in validation_result.items()
            if key != "status"
        } | {
            "available_time_minutes": request.available_time_minutes,
        },

        # 선택 중 위도·경도를 이용해 계산한
        # 대략적인 이동시간 사전검증 결과
        "travel_time_precheck": {
            "estimated_travel_minutes": estimated_travel_minutes,
            "estimated_total_required_minutes": (
                estimated_total_required_minutes
            ),
            "estimated_minimum_required_minutes": (
                estimated_minimum_required_minutes
            ),
            "warning": travel_time_warning,
            "estimated_order": estimated_travel_result[
                "estimated_order"
            ],
        },
    }


@router.post("/recommend/places/validate-selection")
def validate_place_selection_endpoint(
    request: PlaceSelectionValidationRequest,
):
    return validate_place_selection(
        request,
        validate_selected_places_stay_time,
        calculate_estimated_route_travel_minutes,
    )
