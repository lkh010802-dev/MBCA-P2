import math


# 1. 시간 계산에 사용하는 기본 기준값
TIME_BUFFER_MINUTES = 10

# 전체 시간 중 이동시간이 차지하는 비율 기준
# 30% 이하 → 기본 추천
# 30~40% → 후보 유지 + Ranking 감점
# 40% 초과 → 기본 추천에서는 제외
NORMAL_TRAVEL_RATIO = 0.30
EXTENDED_TRAVEL_RATIO = 0.40

# 종료시간이 없을 때 사용하는 실제 이동시간 기준
NORMAL_TRAVEL_MINUTES = 30
EXTENDED_TRAVEL_MINUTES = 60


# 2. 두 좌표 사이의 직선거리 계산
def calculate_straight_distance_km(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float
):
    """
    두 위도·경도 사이의 직선거리를 km 단위로 계산한다.

    지도 API를 호출하지 않고 계산할 수 있기 때문에
    121개 POI를 빠르게 1차 선별할 때 사용한다.

    실제 도로거리나 대중교통 이동거리가 아니라
    지구 곡률을 반영한 두 좌표 사이의 거리다.
    """

    earth_radius_km = 6371

    # 위도·경도를 라디안으로 변환
    lat1 = math.radians(start_latitude)
    lon1 = math.radians(start_longitude)
    lat2 = math.radians(end_latitude)
    lon2 = math.radians(end_longitude)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    # Haversine 공식
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return earth_radius_km * c


# 3. 후보지역에서 실제로 머물 수 있는 시간 계산
def calculate_available_stay_minutes(
    time_window_minutes: int | None,
    start_to_candidate_travel_minutes: int,
    candidate_to_end_location_travel_minutes: int = 0
):
    """
    전체 사용 가능시간에서 이동시간과 10분 버퍼를 제외해
    후보지역에서 실제로 머물 수 있는 시간을 계산한다.

    계산식:

    전체 시간
    - 시작 위치 → 후보지역 이동시간
    - 후보지역 → 다음 일정 위치 이동시간
    - 10분 버퍼
    """

    # 종료시간이 없어 전체 시간창을 계산할 수 없는 경우
    if time_window_minutes is None:
        return None

    available_stay_minutes = (
        time_window_minutes
        - start_to_candidate_travel_minutes
        - candidate_to_end_location_travel_minutes
        - TIME_BUFFER_MINUTES
    )

    # 음수 시간이 나오지 않도록 최소 0분으로 처리
    return max(available_stay_minutes, 0)


# 4. 사용자가 원하는 체류시간을 확보할 수 있는지 확인
def check_duration_feasibility(
    available_stay_minutes: int | None,
    desired_duration_minutes: int | None
):
    """
    후보지역의 실제 체류 가능시간이
    사용자가 원하는 활동시간을 만족하는지 확인한다.
    """

    # 전체 시간창 자체를 계산할 수 없는 경우
    if available_stay_minutes is None:
        return {
            "is_feasible": None,
            "reason": "time_window_missing"
        }

    # 사용자가 희망 체류시간을 따로 말하지 않은 경우
    # 시간 부족으로 후보를 제외하지 않는다.
    if desired_duration_minutes is None:
        return {
            "is_feasible": True,
            "reason": "no_desired_duration"
        }

    # 실제 체류 가능시간이 희망 체류시간 이상인지 확인
    is_feasible = (
        available_stay_minutes
        >= desired_duration_minutes
    )

    return {
        "is_feasible": is_feasible,
        "reason": (
            "enough_time"
            if is_feasible
            else "not_enough_time"
        )
    }


# 5. 전체 시간 대비 이동시간 부담 분류
def classify_travel_time(
    time_window_minutes: int | None,
    start_to_candidate_travel_minutes: int,
    candidate_to_end_location_travel_minutes: int = 0
):
    """
    전체 사용 가능시간 중 이동시간이 차지하는 비율을 계산한다.

    현재 기준:

    30% 이하
    → normal

    30% 초과 ~ 40% 이하
    → penalty

    40% 초과
    → extended
    """

    # 시작 → 후보지역
    # + 후보지역 → 다음 일정 위치
    total_travel_minutes = (
        start_to_candidate_travel_minutes
        + candidate_to_end_location_travel_minutes
    )

    # 전체 시간창을 알 수 없으면
    # 이동시간 비율은 계산할 수 없다.
    if time_window_minutes is None:

        if total_travel_minutes <= NORMAL_TRAVEL_MINUTES:
            travel_level = "normal"

        elif total_travel_minutes <= EXTENDED_TRAVEL_MINUTES:
            travel_level = "penalty"

        else:
            travel_level = "extended"

        return {
            "total_travel_minutes": total_travel_minutes,
            "travel_ratio": None,
            "travel_level": travel_level
        }
    # 전체 시간 중 이동시간이 차지하는 비율
    travel_ratio = (
        total_travel_minutes
        / time_window_minutes
    )

    # 30% 이하 → 기본 추천 후보
    if travel_ratio <= NORMAL_TRAVEL_RATIO:
        travel_level = "normal"

    # 30% 초과 ~ 40% 이하
    # → 후보는 유지하지만 Ranking에서 감점
    elif travel_ratio <= EXTENDED_TRAVEL_RATIO:
        travel_level = "penalty"

    # 40% 초과
    # → 기본 추천에서는 제외하고 확장 후보로 사용
    else:
        travel_level = "extended"

    return {
        "total_travel_minutes": total_travel_minutes,
        "travel_ratio": travel_ratio,
        "travel_level": travel_level
    }


# 6. 우회거리 기준으로 121개 POI를 1차 선별
def preselect_candidates_by_detour(
    candidates: list[dict],
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
    limit: int = 20
):
    """
    각 POI를 들렀을 때 얼마나 동선에서 벗어나는지 계산하고,
    우회거리가 적은 후보부터 상위 N개를 반환한다.

    계산식:

    우회거리
    =
    (시작 → 후보 직선거리 + 후보 → 종료 직선거리)
    - 시작 → 종료 직선거리

    지도 API를 사용하지 않는 저비용 1차 필터다.

    실제 지하철 노선, 도로, 환승시간 등은 반영하지 않으므로
    최종 이동시간 판단에는 사용하지 않는다.
    """

    # 후보지역을 들르지 않고
    # 시작 위치 → 종료 위치로 바로 이동했을 때의 직선거리
    direct_distance_km = calculate_straight_distance_km(
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude
    )

    candidate_results = []

    for candidate in candidates:

        # 시작 위치 → 후보지역 직선거리
        start_to_candidate_km = calculate_straight_distance_km(
            start_latitude,
            start_longitude,
            candidate["latitude"],
            candidate["longitude"]
        )

        # 후보지역 → 다음 일정 위치 직선거리
        candidate_to_end_km = calculate_straight_distance_km(
            candidate["latitude"],
            candidate["longitude"],
            end_latitude,
            end_longitude
        )

        # 후보지역을 경유했을 때의 전체 직선거리
        total_distance_km = (
            start_to_candidate_km
            + candidate_to_end_km
        )

        # 후보지역을 들르면서 추가되는 거리
        detour_distance_km = (
            total_distance_km
            - direct_distance_km
        )

        # 기존 후보 정보에 거리 계산 결과 추가
        candidate_results.append({
            **candidate,
            "start_to_candidate_km":
                start_to_candidate_km,
            "candidate_to_end_km":
                candidate_to_end_km,
            "total_distance_km":
                total_distance_km,
            "detour_distance_km":
                detour_distance_km
        })

    # 우회거리가 적은 후보부터 정렬
    candidate_results.sort(
        key=lambda candidate:
            candidate["detour_distance_km"]
    )

    # 상위 N개만 반환
    return candidate_results[:limit]

# 7. 종료지가 없을 때 시작 위치와 가까운 POI를 1차 선별
def preselect_candidates_by_distance(
    candidates: list[dict],
    start_latitude: float,
    start_longitude: float,
    limit: int = 20
):
    """
    종료 위치가 없는 경우,
    현재 시작 위치에서 가까운 후보지역부터 상위 N개를 반환한다.

    지도 API를 사용하지 않고 직선거리만 계산하는
    저비용 1차 필터다.

    실제 이동시간은 이후 지도 API에서 다시 계산한다.
    """

    candidate_results = []

    for candidate in candidates:

        # 시작 위치 → 후보지역 직선거리
        start_to_candidate_km = calculate_straight_distance_km(
            start_latitude,
            start_longitude,
            candidate["latitude"],
            candidate["longitude"]
        )

        # 기존 후보 정보에 거리 계산 결과 추가
        candidate_results.append({
            **candidate,
            "start_to_candidate_km":
                start_to_candidate_km
        })

    # 시작 위치에서 가까운 후보부터 정렬
    candidate_results.sort(
        key=lambda candidate:
            candidate["start_to_candidate_km"]
    )

    # 상위 N개만 반환
    return candidate_results[:limit]