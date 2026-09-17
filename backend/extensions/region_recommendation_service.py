from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from audit_trace import record

from models import RecommendRequest, StructuredConditions
from conditions import (
    extract_explicit_activity_location,
    extract_explicit_end_location,
    extract_explicit_duration_minutes,
    infer_activity_sequence,
    requests_nearby,
    allows_mountain_activity,
    resolve_start_location,
    resolve_target_location,
    resolve_start_time,
    resolve_end_location,
    resolve_end_time,
    resolve_datetimes,
    calculate_time_window,
    calculate_candidate_arrival_time,
)
from candidate_filter import (
    calculate_available_stay_minutes,
    check_duration_feasibility,
    classify_travel_time,
    preselect_candidates_by_detour,
    preselect_candidates_by_distance,
)
from congestion_service import get_nearest_forecast_congestion
from ranking import (
    convert_congestion_to_score,
    convert_travel_ratio_to_score,
    calculate_final_score,
    convert_travel_minutes_to_score,
)


MAX_REGION_TRAVEL_WORKERS = 3
NEARBY_MAX_ONE_WAY_MINUTES = 20
MAX_ROUTE_CORRIDOR_DETOUR_KM = 1.5


def _get_candidate_travel_pair(
    candidate,
    *,
    start_location,
    end_location,
    transport_mode,
    get_travel_fn,
):
    start_to_candidate = get_travel_fn(
        start_location["x"],
        start_location["y"],
        candidate["longitude"],
        candidate["latitude"],
        transport_mode=transport_mode,
    )
    if (
        start_to_candidate is None
        or "duration_min" not in start_to_candidate
    ):
        return None

    if end_location is None:
        candidate_to_end = {"duration_min": 0}
    else:
        candidate_to_end = get_travel_fn(
            candidate["longitude"],
            candidate["latitude"],
            end_location["x"],
            end_location["y"],
            transport_mode=transport_mode,
        )
        if (
            candidate_to_end is None
            or "duration_min" not in candidate_to_end
        ):
            return None

    return start_to_candidate, candidate_to_end


def recommend_regions(
    request: RecommendRequest,
    *,
    parse_user_intent_fn,
    generate_recommendation_message_fn,
    search_location_fn,
    get_travel_fn,
    load_poi_candidates_fn,
    load_poi_activity_scores_fn,
    get_congestion_data_fn,
    find_proactive_suggestion_fn,
    stored_preferences=None,
):

    current_datetime = datetime.now().astimezone().isoformat()

    if request.auto_course:
        # 자동 코스는 현재 위치와 사용자가 고른 시간이 이미 확정되어 있다.
        # LLM 왕복을 생략해 첫 추천 대기시간과 실패 가능성을 줄인다.
        auto_duration = request.auto_course_duration_minutes or 180
        intent = StructuredConditions(
            desired_duration_min_minutes=auto_duration,
            desired_duration_max_minutes=auto_duration,
            desired_duration_minutes=auto_duration,
            activities=request.preferred_activities,
            transport_mode=request.preferred_transport_mode or "auto",
            space_preference=request.preferred_space,
        ).model_dump()
    else:
        intent = parse_user_intent_fn(
            user_input=request.user_message,
            current_datetime=current_datetime
        )

    conditions = StructuredConditions(**intent)
    if conditions.transport_mode == 'auto' and request.preferred_transport_mode is not None:
        conditions.transport_mode = request.preferred_transport_mode
    if conditions.space_preference is None and request.preferred_space is not None:
        conditions.space_preference = request.preferred_space
    if not conditions.activities and request.preferred_activities:
        conditions.activities = request.preferred_activities
    explicit_activity_location = extract_explicit_activity_location(request.user_message)
    if explicit_activity_location is not None:
        conditions.target_location_text = explicit_activity_location
        conditions.target_location_scope = "area"
    explicit_end_location = extract_explicit_end_location(request.user_message)
    if explicit_end_location is not None:
        conditions.end_location_text = explicit_end_location
    explicit_duration = extract_explicit_duration_minutes(request.user_message)
    if explicit_duration is not None and not request.auto_course:
        conditions.desired_duration_min_minutes = explicit_duration
        conditions.desired_duration_max_minutes = explicit_duration
        conditions.desired_duration_minutes = explicit_duration
    # LLM이 후속 활동을 놓쳐도 원문의 순서를 보수적으로 복구한다.
    # 명시적 거부나 집·숙소에서 쉰다는 문장은 카페로 확대하지 않는다.
    conditions.activities = infer_activity_sequence(
        request.user_message,
        conditions.activities,
    )


    # 5. 사용자 시작 위치 결정
    # request의 GPS와 구조화된 위치 조건을 이용한다.
    resolved_start_location = resolve_start_location(
        request,
        conditions
    )
    # 6. 사용자가 실제로 활동하고 싶은 목적 지역 결정
    # 사용자가 특정 지역을 지정하지 않았다면 missing으로 처리한다.
    resolved_target_location = resolve_target_location(
        conditions
    )

    # 7. 시작시간 / 종료위치 / 종료시간 결정
    resolved_start_time = resolve_start_time(
        conditions
    )

    resolved_end_location = resolve_end_location(
        conditions
    )

    resolved_end_time = resolve_end_time(
        conditions
    )

    # 8. 시작시간과 종료시간을 실제 datetime으로 변환
    resolved_datetimes = resolve_datetimes(
        resolved_start_time,
        resolved_end_time
    )

    # 9. 사용자가 실제로 사용할 수 있는 전체 시간 계산
    time_window = calculate_time_window(
        resolved_datetimes
    )
    # 총 코스 예산과 장소 체류 희망시간은 의미가 다르다.
    # 자동 코스 선택시간은 최우선 총 예산이며, 텍스트 요청은 마감시간으로
    # 계산한 창을 우선하고 그것이 없을 때만 희망 기간을 총 예산으로 사용한다.
    final_available_time = (
        request.auto_course_duration_minutes
        if request.auto_course
        else time_window["time_window_minutes"]
        or conditions.desired_duration_max_minutes
        or conditions.desired_duration_minutes
    )
    # 별도의 마감시간이 있을 때만 desired duration을 최소 체류 요구로 쓴다.
    # 같은 180분을 총 예산과 최소 체류시간에 동시에 적용하면 이동시간 때문에
    # 모든 후보가 거절되는 모순이 발생한다.
    desired_stay_minutes = (
        conditions.desired_duration_minutes
        if (
            time_window["time_window_minutes"] is not None
            and explicit_duration is None
        )
        else None
    )
    record(
        'resolved_conditions',
        final_conditions=conditions.model_dump(),
        resolved_start_location=resolved_start_location,
        resolved_target_location=resolved_target_location,
        resolved_end_location=resolved_end_location,
        departure_datetime=resolved_datetimes["start_datetime"],
        end_datetime=resolved_datetimes["end_datetime"],
        available_time_minutes=final_available_time,
        warnings=(
            ['target_location_used_as_start']
            if resolved_start_location.get('derived_from_target')
            else ['explicit_start_recovered']
            if resolved_start_location['source'] == 'text' and not conditions.start_location_text
            else []
        ),
    )
    
    # 10. 전체 POI를 불러온 뒤 우회거리 기준으로 1차 후보를 선별한다.
    all_candidates = load_poi_candidates_fn()

    # 실제 시작 위치를 좌표 형태로 변환한다.
    if resolved_start_location["source"] == "text":
        start_location = search_location_fn(
            resolved_start_location["location_text"]
        )
        # 지도 검색으로 시작 위치를 찾지 못한 경우
        if start_location is None:
            return {
                "error": "start_location_not_found",
                "message": "시작 위치를 찾을 수 없습니다."
            }

    elif resolved_start_location["source"] == "gps":
        start_location = {
            "x": resolved_start_location["longitude"],
            "y": resolved_start_location["latitude"]
        }

    else:
        return {
            "error": "start_location_missing",
            "message": "시작 위치 정보가 필요합니다."
        }

    # 사용자가 실제로 활동하고 싶은 목적 지역을 좌표 형태로 변환한다.
    if resolved_target_location["source"] == "text":
        target_location = search_location_fn(
            resolved_target_location["location_text"]
        )

        # 지도 검색으로 목적 지역을 찾지 못한 경우
        if target_location is None:
            return {
                "error": "target_location_not_found",
                "message": "활동 목적 지역을 찾을 수 없습니다."
            }

    else:
        target_location = None

    # 현재 지역 추천 후보 초기화
    current_area_candidate = None

    # 사용자가 활동할 목적 지역을 따로 지정하지 않은 경우에만
    # 현재 위치와 가까운 지역을 현재 지역 추천 후보로 확인한다.
    if target_location is None:

        nearest_start_candidates = preselect_candidates_by_distance(
            candidates=all_candidates,
            start_latitude=float(start_location["y"]),
            start_longitude=float(start_location["x"]),
            limit=1,
        )

        if nearest_start_candidates:
            nearest_candidate = nearest_start_candidates[0].copy()

            # MVP에서는 POI 중심좌표와 1km 이내일 경우
            # 현재 지역에 있다고 임시 판단한다.
            if (
                nearest_candidate["start_to_candidate_km"] <= 1.0
                or resolved_start_location["source"] == "text"
            ):
                current_area_candidate = nearest_candidate
                # 명시한 역·장소는 추천의 기준점이다. 인근 POI의 혼잡도와
                # 활동 점수는 재사용하되 이름과 장소 탐색 중심을 바꾸지 않는다.
                if resolved_start_location["source"] == "text":
                    current_area_candidate["AREA_NM"] = resolved_start_location["location_text"]
                    current_area_candidate["latitude"] = float(start_location["y"])
                    current_area_candidate["longitude"] = float(start_location["x"])
                    current_area_candidate["start_to_candidate_km"] = 0.0


    # 실제 종료 위치를 좌표 형태로 변환한다.
    if resolved_end_location["source"] == "text":
        end_location = search_location_fn(
            resolved_end_location["location_text"]
        )
        # 지도 검색으로 종료 위치를 찾지 못한 경우
        if end_location is None:
            return {
                "error": "end_location_not_found",
                "message": "종료 위치를 찾을 수 없습니다."
            }
    else:
        end_location = None

    try:
        proactive_suggestion = find_proactive_suggestion_fn(
            start_location=start_location,
            departure_datetime=resolved_datetimes["start_datetime"],
            end_location=end_location,
            end_datetime=resolved_datetimes["end_datetime"],
            transport_mode=conditions.transport_mode,
            activities=conditions.activities,
        )
    except Exception:
        proactive_suggestion = None

    # 사용자가 활동할 목적 지역을 지정한 경우
    # target 주변의 여러 POI를 1차 후보로 가져온다.
    target_area_candidate = None
    target_area_candidates = []

    if target_location is not None:
       

        target_location_scope = conditions.target_location_scope


        # 사용자가 직접 적은 활동 지역은 GPS보다 우선하는 강한 제약이다.
        # 가장 가까운 POI의 점수 데이터만 빌리되 이름과 장소 검색 중심 좌표는
        # 사용자가 적은 지역 자체로 고정해 옆 역·먼 자치구로 이동하지 않게 한다.
        nearest_target_candidates = preselect_candidates_by_distance(
            candidates=all_candidates,
            start_latitude=float(target_location["y"]),
            start_longitude=float(target_location["x"]),
            limit=1,
        )
        if nearest_target_candidates:
            anchored_target = nearest_target_candidates[0].copy()
            anchored_target["AREA_NM"] = resolved_target_location["location_text"]
            anchored_target["latitude"] = float(target_location["y"])
            anchored_target["longitude"] = float(target_location["x"])
            anchored_target["start_to_candidate_km"] = 0.0
            nearest_target_candidates = [anchored_target]

        # 이 시점의 start_to_candidate_km는
        # 실제 시작 위치가 아니라 target → 후보 거리이므로
        # 별도 필드로 보존한다.
        for candidate in nearest_target_candidates:
            candidate["target_to_candidate_km"] = (
                candidate["start_to_candidate_km"]
            )

        # 실제 시작 위치 → 후보 거리도 다시 계산한다.
        if nearest_target_candidates:

            target_area_candidates = preselect_candidates_by_distance(
                candidates=nearest_target_candidates,
                start_latitude=float(start_location["y"]),
                start_longitude=float(start_location["x"]),
                limit=len(nearest_target_candidates),
            )




    # 사용자가 활동할 목적 지역을 직접 지정한 경우
    # 해당 목적 지역만 추천 후보로 사용한다.
    if target_area_candidates:
        real_candidates = target_area_candidates


    # 목적 지역을 따로 지정하지 않았고 종료지가 있는 경우
    # 시작 → 후보 → 종료 우회거리 기준으로 후보를 선별한다.
    elif end_location is not None:
        real_candidates = preselect_candidates_by_detour(
            candidates=all_candidates,
            start_latitude=float(start_location["y"]),
            start_longitude=float(start_location["x"]),
            end_latitude=float(end_location["y"]),
            end_longitude=float(end_location["x"]),
            limit=20,
        )
        # 다음 일정으로 가는 자연스러운 경로에서 벗어나는 후보는 추천하지 않는다.
        real_candidates = [
            candidate
            for candidate in real_candidates
            if candidate.get("detour_distance_km", float("inf"))
            <= MAX_ROUTE_CORRIDOR_DETOUR_KM
        ]

    # 목적 지역도 없고 종료지도 없는 경우
    # 시작 위치와 가까운 거리 기준으로 후보를 선별한다.
    else:
        real_candidates = preselect_candidates_by_distance(
            candidates=all_candidates,
            start_latitude=float(start_location["y"]),
            start_longitude=float(start_location["x"]),
            limit=20,
        )

    if not allows_mountain_activity(request.user_message, conditions.activities):
        real_candidates = [
            candidate
            for candidate in real_candidates
            if not any(
                token in str(candidate.get("AREA_NM") or "")
                for token in ("관악산", "북한산", "도봉산", "수락산", "정상")
            )
        ]

    # 우회거리로 선별된 후보에 활동 적합도 점수를 연결해 확인한다.
    activity_scores = load_poi_activity_scores_fn()

    # 현재 지역 후보에도 활동 적합도 점수를 연결한다.
    if current_area_candidate is not None:

        current_area_score = activity_scores[
            activity_scores["AREA_CD"] == current_area_candidate["AREA_CD"]
        ]

        if not current_area_score.empty:

            row = current_area_score.iloc[0]

            current_area_candidate["food_score"] = int(row["food_score"])
            current_area_candidate["cafe_score"] = int(row["cafe_score"])
            current_area_candidate["drink_score"] = int(row["drink_score"])
            current_area_candidate["entertainment_score"] = int(row["entertainment_score"])
            current_area_candidate["walk_score"] = int(row["walk_score"])
            current_area_candidate["culture_score"] = int(row["culture_score"])
            current_area_candidate["shopping_score"] = int(row["shopping_score"])

            selected_scores = []

            for activity in conditions.activities:
                score_key = f"{activity}_score"

                if score_key in current_area_candidate:
                    selected_scores.append(
                        current_area_candidate[score_key]
                    )

            if selected_scores:
                current_area_candidate["activity_match_score"] = float(
                sum(selected_scores) / len(selected_scores)
            )
            else:
                current_area_candidate["activity_match_score"] = 0
        else:
            # 현재 지역의 활동 점수 데이터를 찾지 못한 경우
            # 활동 적합도 점수를 0으로 처리한다.
            current_area_candidate["activity_match_score"] = 0

        # 현재 지역 후보의 이동시간, 혼잡도, 최종점수를 계산한다.
    if current_area_candidate is not None:

        # 이미 현재 지역에 있으므로 시작 → 현재 지역 이동시간은 0분이다.
        start_to_current_travel_minutes = 0

        # 종료지가 있는 경우 현재 위치 → 종료지 이동시간을 계산한다.
        if end_location is not None:

            current_to_end = get_travel_fn(
                start_location["x"],
                start_location["y"],
                end_location["x"],
                end_location["y"],
                transport_mode=conditions.transport_mode
            )

            # 선택한 이동수단으로 이동 경로를 구하지 못한 경우
            if (
                current_to_end is None
                or "duration_min" not in current_to_end
            ):
                current_to_end = None

        else:
            current_to_end = {
                "duration_min": 0
            }

        # 종료지까지 이동 가능한 경우에만 점수를 계산한다.
        if current_to_end is not None:

            current_area_candidate["start_to_candidate_travel_minutes"] = (
                start_to_current_travel_minutes
            )

            current_area_candidate["candidate_to_end_travel_minutes"] = (
                current_to_end["duration_min"]
            )
            current_area_candidate["start_to_candidate_transport"] = {
                "mode": "stay",
                "duration_min": 0,
            }
            current_area_candidate["candidate_to_end_transport"] = current_to_end

            current_area_candidate["available_stay_minutes"] = (
                calculate_available_stay_minutes(
                    final_available_time,
                    start_to_current_travel_minutes,
                    current_to_end["duration_min"]
                )
            )

            current_area_candidate["duration_feasibility"] = (
                check_duration_feasibility(
                    current_area_candidate["available_stay_minutes"],
                    desired_stay_minutes
                )
            )

            current_area_candidate["travel_time_classification"] = (
                classify_travel_time(
                    final_available_time,
                    start_to_current_travel_minutes,
                    current_to_end["duration_min"]
                )
            )

            current_area_candidate["arrival_datetime"] = (
                calculate_candidate_arrival_time(
                    resolved_datetimes["start_datetime"],
                    0
                )
            )

            if final_available_time is not None:
                current_area_candidate["travel_score"] = (
                    convert_travel_ratio_to_score(
                        current_area_candidate[
                            "travel_time_classification"
                        ]["travel_ratio"]
                    )
                )
            else:
                current_area_candidate["travel_score"] = (
                    convert_travel_minutes_to_score(
                        current_area_candidate[
                            "travel_time_classification"
                        ]["total_travel_minutes"]
                    )
                )

            current_congestion_data = get_congestion_data_fn(
                current_area_candidate["AREA_CD"]
            )

            # 혼잡도 데이터가 있는 경우
            if current_congestion_data:

                current_forecast_congestion = (
                    get_nearest_forecast_congestion(
                        current_congestion_data,
                        current_area_candidate["arrival_datetime"]
                    )
                )

            else:
                current_forecast_congestion = None


            # 예측 혼잡도까지 정상적으로 있는 경우
            if current_forecast_congestion:

                current_area_candidate["forecast_congestion"] = (
                    current_forecast_congestion
                )

                current_area_candidate["congestion_score"] = (
                    convert_congestion_to_score(
                        current_forecast_congestion["FCST_CONGEST_LVL"]
                    )
                )

            # 혼잡도 데이터를 구하지 못한 경우 중립 점수 3점 처리
            else:

                current_area_candidate["forecast_congestion"] = None
                current_area_candidate["congestion_score"] = 3

            current_area_candidate["final_score"] = (
                calculate_final_score(
                    activity_score=current_area_candidate[
                        "activity_match_score"
                    ],
                    travel_score=current_area_candidate["travel_score"],
                    congestion_score=current_area_candidate[
                        "congestion_score"
                    ],
                    has_activity=bool(conditions.activities)
                )
            )
        else:
            # 종료지까지 이동 경로를 확인할 수 없으면
            # 현재 지역 추천 후보에서 제외한다.
            current_area_candidate = None
    # 현재 지역에서 사용자가 원하는 체류시간을 확보할 수 없는 경우
    # 현재 지역 추천에서 제외한다.
    if (
        current_area_candidate is not None
        and current_area_candidate["duration_feasibility"]["is_feasible"] is False
    ):
        current_area_candidate = None

    selected_area_codes = [
        candidate["AREA_CD"]
        for candidate in real_candidates
    ]

    

    selected_activity_scores = activity_scores[
        activity_scores["AREA_CD"].isin(selected_area_codes)
    ]

    distance_map = {
        candidate["AREA_CD"]: {
            "detour_distance_km": candidate.get("detour_distance_km"),
            "start_to_candidate_km": candidate.get("start_to_candidate_km"),
            "target_to_candidate_km": candidate.get("target_to_candidate_km"),
        }
        for candidate in real_candidates
    }
    candidate_location_map = {
        candidate["AREA_CD"]: {
            "latitude": candidate["latitude"],
            "longitude": candidate["longitude"],
        }
        for candidate in real_candidates
    }
    candidate_name_map = {
        candidate["AREA_CD"]: candidate["AREA_NM"]
        for candidate in real_candidates
    }
    scored_candidates = []

    for _, row in selected_activity_scores.iterrows():
        scored_candidates.append({
            "AREA_CD": row["AREA_CD"],
            # 사용자가 직접 적은 활동 지역은 가장 가까운 POI의 점수만 빌린다.
            # 화면 이름은 점수 원본 지역명이 아니라 사용자의 지역명을 유지한다.
            "AREA_NM": candidate_name_map[row["AREA_CD"]],
            "latitude": candidate_location_map[row["AREA_CD"]]["latitude"],
            "longitude": candidate_location_map[row["AREA_CD"]]["longitude"],
            "detour_distance_km": distance_map[row["AREA_CD"]]["detour_distance_km"],
            "start_to_candidate_km": distance_map[row["AREA_CD"]]["start_to_candidate_km"],
            "target_to_candidate_km": distance_map[row["AREA_CD"]]["target_to_candidate_km"],
            "food_score": int(row["food_score"]),
            "cafe_score": int(row["cafe_score"]),
            "drink_score": int(row["drink_score"]),
            "entertainment_score": int(row["entertainment_score"]),
            "walk_score": int(row["walk_score"]),
            "culture_score": int(row["culture_score"]),
            "shopping_score": int(row["shopping_score"]),
        })

    # 사용자가 선택한 활동들의 점수만 평균낸다.
    for candidate in scored_candidates:

        selected_scores = []

        for activity in conditions.activities:
            score_key = f"{activity}_score"

            if score_key in candidate:
                selected_scores.append(
                    candidate[score_key]
                )

        if selected_scores:
            candidate["activity_match_score"] = (
                sum(selected_scores) / len(selected_scores)
            )
        else:
            candidate["activity_match_score"] = 0

    # 시작 위치와 가까운 순서대로 정렬한다.
    distance_ranked_candidates = sorted(
        scored_candidates,
        key=lambda candidate: candidate["start_to_candidate_km"]
    )

    api_candidates = []

    # 사용자가 원하는 활동을 지정한 경우
    if conditions.activities:

        # 활동 적합도가 높은 순서대로 정렬한다.
        activity_ranked_candidates = sorted(
            scored_candidates,
            key=lambda candidate: candidate["activity_match_score"],
            reverse=True
        )

        # 현재 지역을 제외하고 활동 적합도 상위 3개를 넣는다.
        activity_candidate_count = 0

        for candidate in activity_ranked_candidates:

            # 현재 지역은 별도로 처리한다.
            if (
                current_area_candidate is not None
                and candidate["AREA_CD"] == current_area_candidate["AREA_CD"]
            ):
                continue

            api_candidates.append(candidate)
            activity_candidate_count += 1

            if activity_candidate_count >= 3:
                break

        # 가까운 지역을 추가하여 최대 5개 후보를 만든다.
        for candidate in distance_ranked_candidates:

            if (
                current_area_candidate is not None
                and candidate["AREA_CD"] == current_area_candidate["AREA_CD"]
            ):
                continue

            if candidate["AREA_CD"] not in [
                selected["AREA_CD"]
                for selected in api_candidates
            ]:
                api_candidates.append(candidate)

            if len(api_candidates) >= 5:
                break

    # 사용자가 특정 활동을 지정하지 않은 경우
    else:

        # 활동점수로 선별하지 않고 가까운 지역 5개를 사용한다.
        for candidate in distance_ranked_candidates:

            if (
                current_area_candidate is not None
                and candidate["AREA_CD"] == current_area_candidate["AREA_CD"]
            ):
                continue

            api_candidates.append(candidate)

            if len(api_candidates) >= 5:
                break

    # 상위 후보의 실제 대중교통 이동시간을 확인한다.

    valid_api_candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_REGION_TRAVEL_WORKERS
    ) as executor:
        travel_pairs = list(executor.map(
            lambda candidate: _get_candidate_travel_pair(
                candidate,
                start_location=start_location,
                end_location=end_location,
                transport_mode=conditions.transport_mode,
                get_travel_fn=get_travel_fn,
            ),
            api_candidates,
        ))

    for candidate, travel_pair in zip(api_candidates, travel_pairs):
        if travel_pair is None:
            continue

        start_to_candidate, candidate_to_end = travel_pair

        if (
            (request.auto_course or requests_nearby(request.user_message))
            and start_to_candidate["duration_min"] > NEARBY_MAX_ONE_WAY_MINUTES
        ):
            continue

        candidate["start_to_candidate_travel_minutes"] = (
            start_to_candidate["duration_min"]
        )

        candidate["candidate_to_end_travel_minutes"] = (
            candidate_to_end["duration_min"]
        )
        candidate["start_to_candidate_transport"] = start_to_candidate
        candidate["candidate_to_end_transport"] = candidate_to_end

        candidate["available_stay_minutes"] = (
            calculate_available_stay_minutes(
                final_available_time,
                start_to_candidate["duration_min"],
                candidate_to_end["duration_min"]
            )
        )

        candidate["duration_feasibility"] = (
            check_duration_feasibility(
                candidate["available_stay_minutes"],
                desired_stay_minutes
            )
        )

        candidate["travel_time_classification"] = (
            classify_travel_time(
                final_available_time,
                start_to_candidate["duration_min"],
                candidate_to_end["duration_min"],
            )
        )

        candidate["arrival_datetime"] = (
            calculate_candidate_arrival_time(
                resolved_datetimes["start_datetime"],
                start_to_candidate["duration_min"]
            )
        )

        # 종료시간이 있는 경우 → 전체 시간 대비 이동 비율로 점수 계산
        if final_available_time is not None:
            candidate["travel_score"] = convert_travel_ratio_to_score(
                candidate["travel_time_classification"]["travel_ratio"]
            )

        # 종료시간이 없는 경우 → 실제 이동시간으로 점수 계산
        else:
            candidate["travel_score"] = convert_travel_minutes_to_score(
                candidate["travel_time_classification"]["total_travel_minutes"]
            )

        congestion_data = get_congestion_data_fn(
            candidate["AREA_CD"]
        )

        # 혼잡도 데이터가 있는 경우
        if congestion_data:
            forecast_congestion = get_nearest_forecast_congestion(
                congestion_data,
                candidate["arrival_datetime"]
            )
        else:
            forecast_congestion = None

        # 예측 혼잡도까지 정상적으로 있는 경우
        if forecast_congestion:
            candidate["forecast_congestion"] = forecast_congestion

            candidate["congestion_score"] = convert_congestion_to_score(
                forecast_congestion["FCST_CONGEST_LVL"]
            )

        # 혼잡도 데이터를 구하지 못한 경우 중립 점수 3점 처리
        else:
            candidate["forecast_congestion"] = None
            candidate["congestion_score"] = 3

        candidate["final_score"] = calculate_final_score(
            activity_score=candidate["activity_match_score"],
            travel_score=candidate["travel_score"],
            congestion_score=candidate["congestion_score"],
            has_activity=bool(conditions.activities)
        )

        valid_api_candidates.append(candidate)
    api_candidates = valid_api_candidates
    recommended_candidates = []
    extended_candidates = []
    excluded_candidates = []

    for candidate in api_candidates:

        if candidate["duration_feasibility"]["is_feasible"] is False:
            excluded_candidates.append(candidate)

        elif candidate["travel_time_classification"]["travel_level"] == "extended":
            extended_candidates.append(candidate)

        else:
            recommended_candidates.append(candidate)
    # 추천 가능한 후보를 최종 추천점수가 높은 순서대로 정렬한다.
    recommended_candidates.sort(
        key=lambda candidate: candidate["final_score"],
        reverse=True
    )

    # 사용자가 활동 목적 지역을 지정한 경우
    # 명시한 목적 지역을 다른 지역의 높은 활동 점수가 덮어쓰지 않도록
    # 목적 좌표에 가장 가까운 유효 후보를 최종 target으로 선정한다.
    if target_location is not None:

        if recommended_candidates:
            target_area_candidate = min(
                recommended_candidates,
                key=lambda candidate: candidate.get("target_to_candidate_km", float("inf")),
            )
        else:
            target_area_candidate = None


    # 이동 부담이 큰 확장 후보는
    # 총 이동시간이 짧은 후보를 우선하고,
    # 이동시간이 같으면 최종 추천점수가 높은 후보를 우선한다.
    extended_candidates.sort(
        key=lambda candidate: (
            candidate["travel_time_classification"]["total_travel_minutes"],
            -candidate["final_score"]
        )
    )
    # 사용자가 활동 목적 지역을 따로 지정하지 않은 경우에만
    # 기존 방식대로 다른 추천 지역 상위 3개를 선정한다.
    other_area_candidates = []

    if target_location is None:

        for candidate in recommended_candidates:

            # 현재 지역은 별도로 보여주므로
            # 다른 지역 추천 목록에서는 제외한다.
            if (
                current_area_candidate is not None
                and candidate["AREA_CD"] == current_area_candidate["AREA_CD"]
            ):
                continue

            other_area_candidates.append(candidate)

            if len(other_area_candidates) >= 3:
                break

    # 추천 가능한 지역이 하나도 없는 경우
    if (
        target_area_candidate is None
        and current_area_candidate is None
        and not other_area_candidates
        and not extended_candidates
    ):
        return {
            "error": "no_recommendation_candidates",
            "message": "현재 조건에서 추천 가능한 지역을 찾지 못했습니다."
        }

    # 사용자가 활동 목적 지역을 직접 지정한 경우
    if target_location is not None:
        recommendation_result = {
            "target_area": target_area_candidate,
            "current_area": None,
            "other_areas": [],
            "extended_areas": extended_candidates,
        }

    # 활동 목적 지역을 지정하지 않은 경우
    # 기존 지역 추천 결과를 그대로 사용한다.
    else:
        recommendation_result = {
            "target_area": None,
            "current_area": current_area_candidate,
            "other_areas": other_area_candidates,
            "extended_areas": extended_candidates,
        }

    recommendation_message = generate_recommendation_message_fn(
        user_message=request.user_message,
        recommendation_result=recommendation_result
    )

    return {
        "recommendation_message": recommendation_message,
        "proactive_suggestion": proactive_suggestion,
        "recommendation_context": {
            "activities": conditions.activities,
            "activity_sequence": conditions.activities,
            "transport_mode": conditions.transport_mode,
            "space_preference": conditions.space_preference,
            "companions": conditions.companions,
            "budget_max": conditions.budget_max,
            "budget_preference": conditions.budget_preference,
            "start_location": {
                "latitude": start_location["y"],
                "longitude": start_location["x"],
            },
            "departure_datetime": resolved_datetimes["start_datetime"],
            "end_location": (
                {
                    "latitude": end_location["y"],
                    "longitude": end_location["x"],
                }
                if end_location is not None
                else None
            ),
            "end_datetime": resolved_datetimes["end_datetime"],
            "available_time_minutes": final_available_time,
        },
        "target_area": recommendation_result["target_area"],
        "current_area": recommendation_result["current_area"],
        "other_areas": recommendation_result["other_areas"],
        "extended_areas": recommendation_result["extended_areas"],
    }
