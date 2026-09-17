from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from models import RecommendRequest, StructuredConditions
from conditions import (
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
ACTIVITY_PREFERENCE_BONUSES = {
    4: 0.1,
    5: 0.2,
}


def _merge_stored_preferences(conditions, stored_preferences):
    if not stored_preferences:
        return {}

    if conditions.space_preference is None:
        conditions.space_preference = stored_preferences.get(
            "space_preference"
        )

    if conditions.transport_mode == "auto":
        conditions.transport_mode = (
            stored_preferences.get("transport_mode")
            or conditions.transport_mode
        )

    return stored_preferences.get("activity_preferences") or {}


def _calculate_activity_match_score(
    candidate,
    activities,
    activity_preferences,
):
    selected_scores = []

    for activity in activities:
        score_key = f"{activity}_score"
        if score_key not in candidate:
            continue

        score = candidate[score_key]
        bonus = ACTIVITY_PREFERENCE_BONUSES.get(
            activity_preferences.get(activity),
            0,
        )
        selected_scores.append(min(5.0, score + bonus))

    if not selected_scores:
        return 0

    return sum(selected_scores) / len(selected_scores)


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

    current_datetime = datetime.now(ZoneInfo("Asia/Seoul"))

    intent = parse_user_intent_fn(
        user_input=request.user_message,
        current_datetime=current_datetime.isoformat()
    )

    conditions = StructuredConditions(**intent)
    activity_preferences = _merge_stored_preferences(
        conditions,
        stored_preferences,
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
        conditions,
        current_datetime=current_datetime,
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
        resolved_end_time,
        current_datetime=current_datetime,
    )

    # 9. 사용자가 실제로 사용할 수 있는 전체 시간 계산
    time_window = calculate_time_window(
        resolved_datetimes
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
            nearest_candidate = nearest_start_candidates[0]

            # MVP에서는 POI 중심좌표와 1km 이내일 경우
            # 현재 지역에 있다고 임시 판단한다.
            if nearest_candidate["start_to_candidate_km"] <= 1.0:
                current_area_candidate = nearest_candidate


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


        if target_location_scope == "place":
            # 사용자가 특정 장소를 지정한 경우
            # 지도 검색으로 찾은 실제 위치와 가장 가까운
            # 121개 POI 하나를 대표 지역으로 사용한다.
            nearest_target_candidates = preselect_candidates_by_distance(
                candidates=all_candidates,
                start_latitude=float(target_location["y"]),
                start_longitude=float(target_location["x"]),
                limit=1,
            )

        else:
            # 사용자가 강남, 홍대처럼 넓은 지역을 지정한 경우
            # 해당 지역 주변 여러 POI를 후보로 만든 뒤
            # 이후 활동 적합도, 이동시간, 혼잡도 등을 함께 평가한다.
            nearest_target_candidates = preselect_candidates_by_distance(
                candidates=all_candidates,
                start_latitude=float(target_location["y"]),
                start_longitude=float(target_location["x"]),
                limit=10,
            )

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

    # 목적 지역도 없고 종료지도 없는 경우
    # 시작 위치와 가까운 거리 기준으로 후보를 선별한다.
    else:
        real_candidates = preselect_candidates_by_distance(
            candidates=all_candidates,
            start_latitude=float(start_location["y"]),
            start_longitude=float(start_location["x"]),
            limit=20,
        )

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

            current_area_candidate["activity_match_score"] = float(
                _calculate_activity_match_score(
                    current_area_candidate,
                    conditions.activities,
                    activity_preferences,
                )
            )
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

            current_area_candidate["available_stay_minutes"] = (
                calculate_available_stay_minutes(
                    time_window["time_window_minutes"],
                    start_to_current_travel_minutes,
                    current_to_end["duration_min"]
                )
            )

            current_area_candidate["duration_feasibility"] = (
                check_duration_feasibility(
                    current_area_candidate["available_stay_minutes"],
                    conditions.desired_duration_minutes
                )
            )

            current_area_candidate["travel_time_classification"] = (
                classify_travel_time(
                    time_window["time_window_minutes"],
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

            if time_window["time_window_minutes"] is not None:
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
    scored_candidates = []

    for _, row in selected_activity_scores.iterrows():
        scored_candidates.append({
            "AREA_CD": row["AREA_CD"],
            "AREA_NM": row["AREA_NM"],
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

        candidate["activity_match_score"] = (
            _calculate_activity_match_score(
                candidate,
                conditions.activities,
                activity_preferences,
            )
        )

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

        candidate["start_to_candidate_travel_minutes"] = (
            start_to_candidate["duration_min"]
        )

        candidate["candidate_to_end_travel_minutes"] = (
            candidate_to_end["duration_min"]
        )

        candidate["available_stay_minutes"] = (
            calculate_available_stay_minutes(
                time_window["time_window_minutes"],
                start_to_candidate["duration_min"],
                candidate_to_end["duration_min"]
            )
        )

        candidate["duration_feasibility"] = (
            check_duration_feasibility(
                candidate["available_stay_minutes"],
                conditions.desired_duration_minutes
            )
        )

        candidate["travel_time_classification"] = (
            classify_travel_time(
                time_window["time_window_minutes"],
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
        if time_window["time_window_minutes"] is not None:
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
    # 모든 평가를 통과한 후보 중 최종점수가 가장 높은 지역을
    # 최종 target 지역으로 선정한다.
    if target_location is not None:

        if recommended_candidates:
            target_area_candidate = recommended_candidates[0]
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
            "activity_preferences": {
                activity: activity_preferences[activity]
                for activity in conditions.activities
                if activity in activity_preferences
            },
            "transport_mode": conditions.transport_mode,
            "space_preference": conditions.space_preference,
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
            "available_time_minutes": time_window["time_window_minutes"],
        },
        "target_area": recommendation_result["target_area"],
        "current_area": recommendation_result["current_area"],
        "other_areas": recommendation_result["other_areas"],
        "extended_areas": recommendation_result["extended_areas"],
    }
