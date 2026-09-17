import logging
from threading import Lock
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from auth_routes import router as auth_router
from course_routes import (
    calculate_course as calculate_course_route,
    router as course_router,
)
from place_routes import (
    recommend_actual_places as recommend_actual_places_route,
    recommend_more_actual_places as recommend_more_actual_places_route,
    validate_place_selection as validate_place_selection_route,
    router as place_router,
)
from region_routes import (
    create_region_router,
)
from navigation_routes import router as navigation_router
from user_data_routes import router as user_data_router
from adventure_routes import router as adventure_router
from preference_routes import router as preference_router

from place_recommendation_service import recommend_places
from region_recommendation_service import recommend_regions
from proactive_recommendation_service import find_proactive_suggestion
from place_recommendation_cache import (
    create_place_recommendation_page,
    get_next_place_recommendation_page,
)

from models import (
    RecommendRequest,
    PlaceRecommendRequest,
    PlaceRecommendMoreRequest,
    PlaceSelectionValidationRequest,
    CourseCalculationRequest,
)

from llm_service import (
    parse_user_intent,
    generate_recommendation_message,
)

from map_service import (
    search_location,
    get_travel,
)

from poi import load_poi_candidates

from activity_score import load_poi_activity_scores

from congestion_service import get_congestion_data

from stay_time_validation import (
    validate_selected_places_stay_time,
    calculate_estimated_route_travel_minutes,
)

from course_order_optimizer import optimize_course_order


performance_logger = logging.getLogger("uvicorn.error")


# 1. FastAPI 앱 생성
app = FastAPI()
from audit_trace import AuditMiddleware
app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https://[a-z0-9-]+\.trycloudflare\.com|http://192\.168\.\d+\.\d+:5173",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OBSERVED_API_PATHS = {
    "/recommend",
    "/recommend/places",
    "/recommend/places/more",
    "/recommend/course",
    "/route-preview",
}


@app.middleware("http")
async def log_observed_api_request(request: Request, call_next):
    """핵심 추천 흐름의 상태 코드와 소요시간을 한 줄 형식으로 남긴다."""
    if request.url.path not in OBSERVED_API_PATHS:
        return await call_next(request)
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        performance_logger.exception(
            "[API-ERROR] method=%s path=%s elapsed=%.4fs",
            request.method,
            request.url.path,
            perf_counter() - started,
        )
        raise
    log = performance_logger.warning if response.status_code >= 500 else performance_logger.info
    log(
        "[API] method=%s path=%s status=%d elapsed=%.4fs",
        request.method,
        request.url.path,
        response.status_code,
        perf_counter() - started,
    )
    return response
app.include_router(auth_router)
app.include_router(course_router)
app.include_router(place_router)
app.include_router(navigation_router)
app.include_router(user_data_router)
app.include_router(adventure_router)
# 기존 프론트가 사용하는 /users/me/preferences 계약은 user_data_router가
# 유지한다. 최신 ML 선호도 계약은 충돌을 피하도록 별도 경로로 노출한다.
app.include_router(preference_router, prefix="/ml")


# 2. 서버 기본 동작 확인
@app.get("/")
def root():
    return {
        "message": "KOALA backend",
        "version": "mvp2-integrated-extensions",
        "entrypoint": "run:app",
    }


# 3. 서울 121개 POI 데이터 로드 테스트
@app.get("/test-poi")
def test_poi():

    candidates = load_poi_candidates()

    return {
        "candidate_count": len(candidates),
        "candidates": candidates
    }


def recommend(
    request: RecommendRequest,
    stored_preferences: dict | None = None,
):
    """기존 직접 호출 테스트를 위한 호환 함수."""

    metrics = {
        name: {"seconds": 0.0, "calls": 0}
        for name in (
            "intent_llm",
            "proactive",
            "proactive_travel",
            "region_travel",
            "congestion",
            "message_llm",
            "activity_score",
            "poi_load",
        )
    }
    metrics_lock = Lock()

    def measured(name, function):
        def call(*args, **kwargs):
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = perf_counter() - started
                with metrics_lock:
                    metrics[name]["seconds"] += elapsed
                    metrics[name]["calls"] += 1

        return call

    measured_proactive_travel = measured("proactive_travel", get_travel)

    def measured_proactive(**kwargs):
        return find_proactive_suggestion(
            **kwargs,
            get_travel_fn=measured_proactive_travel,
        )

    total_started = perf_counter()
    try:
        return recommend_regions(
            request,
            parse_user_intent_fn=measured("intent_llm", parse_user_intent),
            generate_recommendation_message_fn=measured(
                "message_llm",
                generate_recommendation_message,
            ),
            search_location_fn=search_location,
            get_travel_fn=measured("region_travel", get_travel),
            load_poi_candidates_fn=measured("poi_load", load_poi_candidates),
            load_poi_activity_scores_fn=measured(
                "activity_score",
                load_poi_activity_scores,
            ),
            get_congestion_data_fn=measured(
                "congestion",
                get_congestion_data,
            ),
            find_proactive_suggestion_fn=measured(
                "proactive",
                measured_proactive,
            ),
            stored_preferences=stored_preferences,
        )
    finally:
        performance_logger.info(
            "[PERFORMANCE] total=%.4fs intent_llm=%.4fs "
            "proactive=%.4fs proactive_travel=%.4fs calls=%d "
            "region_travel=%.4fs calls=%d congestion=%.4fs calls=%d "
            "message_llm=%.4fs activity_score=%.4fs poi_load=%.4fs",
            perf_counter() - total_started,
            metrics["intent_llm"]["seconds"],
            metrics["proactive"]["seconds"],
            metrics["proactive_travel"]["seconds"],
            metrics["proactive_travel"]["calls"],
            metrics["region_travel"]["seconds"],
            metrics["region_travel"]["calls"],
            metrics["congestion"]["seconds"],
            metrics["congestion"]["calls"],
            metrics["message_llm"]["seconds"],
            metrics["activity_score"]["seconds"],
            metrics["poi_load"]["seconds"],
        )


app.include_router(create_region_router(recommend))


def recommend_actual_places(
    request: PlaceRecommendRequest
):
    """기존 직접 호출 테스트를 위한 호환 함수."""

    return recommend_actual_places_route(
        request,
        recommend_places,
        create_place_recommendation_page,
    )


def recommend_more_actual_places(
    request: PlaceRecommendMoreRequest
):
    """기존 직접 호출 테스트를 위한 호환 함수."""

    return recommend_more_actual_places_route(
        request,
        get_next_place_recommendation_page,
    )


def validate_place_selection(
    request: PlaceSelectionValidationRequest,
):
    """기존 직접 호출 테스트를 위한 호환 함수."""

    return validate_place_selection_route(
        request,
        validate_selected_places_stay_time,
        calculate_estimated_route_travel_minutes,
    )


def calculate_course(
    request: CourseCalculationRequest,
):
    """기존 직접 호출 테스트를 위한 호환 함수."""

    return calculate_course_route(
        request,
        optimize_course_order_fn=optimize_course_order,
    )
