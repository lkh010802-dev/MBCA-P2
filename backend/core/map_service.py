import os
import requests

from dotenv import load_dotenv


# 1. Kakao API 키 불러오기
# .env 파일에 저장된 KAKAO_REST_API_KEY를 사용한다.
load_dotenv()

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
ACTUAL_ROUTE_WALK_THRESHOLD_KM = 1.5
PUBLIC_TRANSIT_WALK_FALLBACK_MAX_DISTANCE_M = 500


# 2. Kakao API 요청에 사용할 인증 헤더 생성
def kakao_headers():
    return {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"
    }


# 3. 장소명 / 주소 → 좌표 변환
def search_location(query: str):
    """
    사용자가 입력한 장소명 또는 주소를
    Kakao Local API를 이용해 좌표로 변환한다.

    검색 순서:
    1. 키워드 장소 검색
       예) 강남역, 롯데월드, 서울역

    2. 키워드 검색 결과가 없으면 주소 검색
       예) 서울특별시 강남구 테헤란로 152

    반환:
    {
        "name": 장소명,
        "address": 주소,
        "x": 경도,
        "y": 위도
    }

    장소와 주소 모두 검색되지 않으면 None을 반환한다.
    """

    # 3-1. 키워드 장소 검색
    keyword_url = (
        "https://dapi.kakao.com/v2/local/search/keyword.json"
    )

    try:
        response = requests.get(
            keyword_url,
            headers=kakao_headers(),
            params={
                "query": query
            },
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # 검색 결과가 있으면 첫 번째 장소 사용
    if data.get("documents"):

        place = data["documents"][0]

        try:
            return {
                # 실제 Kakao 장소명
                "name": place.get(
                    "place_name",
                    query
                ),

                # 도로명 주소가 있으면 우선 사용하고
                # 없으면 지번 주소 사용
                "address": (
                    place.get("road_address_name")
                    or place.get("address_name")
                ),

                # x = 경도(Longitude)
                "x": float(place["x"]),

                # y = 위도(Latitude)
                "y": float(place["y"])
            }

        except (KeyError, TypeError, ValueError):
            return None

    # 3-2. 키워드 검색 결과가 없으면 주소 검색
    address_url = (
        "https://dapi.kakao.com/v2/local/search/address.json"
    )

    try:
        response = requests.get(
            address_url,
            headers=kakao_headers(),
            params={
                "query": query
            },
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # 주소 검색 결과가 있으면 첫 번째 결과 사용
    if data.get("documents"):

        place = data["documents"][0]

        try:
            return {
                "name": query,
                "address": place.get("address_name"),
                "x": float(place["x"]),
                "y": float(place["y"])
            }

        except (KeyError, TypeError, ValueError):
            return None

    # 장소명과 주소 모두 검색되지 않은 경우
    return None

# 4. 좌표 기준 주변 장소 카테고리 검색
def search_places_by_category(
    latitude: float,
    longitude: float,
    category_code: str,
    radius: int = 2000,
    size: int = 15,
):
    """
    특정 좌표를 기준으로 주변 장소를
    Kakao Local API 카테고리 검색으로 조회한다.

    주요 카테고리 코드:
    - FD6: 음식점
    - CE7: 카페
    - CT1: 문화시설
    - AT4: 관광명소
    - AD5: 숙박

    radius는 검색 반경이며 단위는 m이다.
    기본값은 2000m(2km)이다.

    반환 결과는 기준 좌표와 가까운 순서로 정렬한다.
    """

    url = (
        "https://dapi.kakao.com/"
        "v2/local/search/category.json"
    )

    params = {
        "category_group_code": category_code,

        # x = 경도
        "x": longitude,

        # y = 위도
        "y": latitude,

        # 검색 반경(m)
        "radius": radius,

        # 한 번에 받을 장소 수
        "size": size,

        # 기준 좌표와 가까운 순서
        "sort": "distance",
    }

    response = requests.get(
        url,
        headers=kakao_headers(),
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    return data.get(
        "documents",
        []
    )


def search_places_by_keyword(
    latitude: float,
    longitude: float,
    query: str,
    radius: int = 2000,
    size: int = 15,
):
    """특정 좌표 주변의 장소를 키워드와 거리순으로 조회한다."""

    url = (
        "https://dapi.kakao.com/"
        "v2/local/search/keyword.json"
    )

    response = requests.get(
        url,
        headers=kakao_headers(),
        params={
            "query": query,
            "x": longitude,
            "y": latitude,
            "radius": radius,
            "size": size,
            "sort": "distance",
        },
        timeout=10,
    )

    response.raise_for_status()

    return response.json().get("documents", [])

# 5. 좌표 → 행정구역 변환
def get_region_from_coordinates(
    latitude: float,
    longitude: float,
):
    """
    위도 / 경도를 기준으로 해당 위치의 행정구역을 조회한다.

    Kakao Local API의 좌표 → 행정구역 변환 기능을 사용한다.

    반환 예시:
    {
        "sido_name": "서울특별시",
        "sigungu_name": "마포구",
        "dong_name": "서교동",
        "region_code": "1144066000"
    }

    행정동(H) 정보를 우선 사용하며,
    행정동 결과가 없는 경우 첫 번째 검색 결과를 사용한다.

    주의:
    region_code는 Kakao가 반환하는 행정구역 코드이며
    TourAPI의 signguCd와 동일한 값이라고 가정하지 않는다.
    """

    url = (
        "https://dapi.kakao.com/"
        "v2/local/geo/coord2regioncode.json"
    )

    params = {
        # x = 경도(Longitude)
        "x": longitude,

        # y = 위도(Latitude)
        "y": latitude,
    }

    response = requests.get(
        url,
        headers=kakao_headers(),
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    documents = data.get(
        "documents",
        []
    )

    # 행정구역 검색 결과가 없는 경우
    if not documents:
        return None

    # region_type:
    # H = 행정동
    # B = 법정동
    #
    # 실제 서비스에서는 행정동 정보를 우선 사용한다.
    region = next(
        (
            document
            for document in documents
            if document.get("region_type") == "H"
        ),
        documents[0],
    )

    return {
        # 시 / 도
        "sido_name":
            region.get("region_1depth_name"),

        # 시 / 군 / 구
        "sigungu_name":
            region.get("region_2depth_name"),

        # 읍 / 면 / 동
        "dong_name":
            region.get("region_3depth_name"),

        # Kakao 행정구역 코드
        "region_code":
            region.get("code"),
    }


# 6. 대중교통 경로 조회
def get_transit(
    start_x,
    start_y,
    end_x,
    end_y
):
    """
    Kakao 대중교통 Routing API를 이용해
    두 좌표 사이의 실제 대중교통 경로를 조회한다.

    경로에는 도보 / 버스 / 지하철 구간이 포함될 수 있다.

    주요 반환값:
    - 전체 이동거리
    - 전체 이동시간
    - 환승 횟수
    - 교통요금
    - 버스 / 지하철 / 도보 세부 경로
    """

    url = (
        "https://dapi.kakao.com/"
        "v2/routing/publictraffic"
    )

    params = {
        "start_x": start_x,
        "start_y": start_y,
        "end_x": end_x,
        "end_y": end_y
    }

    try:
        response = requests.get(
            url,
            headers=kakao_headers(),
            params=params,
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError):
        return None

    if not isinstance(data, dict) or data.get("status") != "OK":
        return None

    try:
        # 여러 추천 경로 중 현재는 첫 번째 경로 사용
        route = data["routes"][0]

        # 전체 경로 정보
        properties = route["properties"]

        # 세부 이동 경로를 저장할 리스트
        paths = []

        # 전체 경로를 도보 / 버스 / 지하철 구간별로 나눠 저장
        for step in route["steps"]:

            step_properties = step["properties"]

            # WALKING / BUS / SUBWAY
            step_type = step_properties["type"]

            # 버스 번호 또는 지하철 노선 정보
            vehicles = step_properties.get(
                "vehicles",
                []
            )

            vehicle_name = None

            if vehicles:
                vehicle_name = vehicles[0].get(
                    "name"
                )

            paths.append({
                # WALKING / BUS / SUBWAY
                "type": step_type,

                # 예: 2호선, 341번 버스
                "vehicle": vehicle_name,

                # 이동 안내문
                "guidance":
                    step_properties.get("guidance"),

                # 해당 구간 거리
                "distance":
                    step_properties.get("distance"),

                # 해당 구간 이동시간
                "time":
                    step_properties.get("time"),

                # 지도에 경로를 표시할 때 사용할 좌표
                "points":
                    step["path"]["points"]
            })

        total_time = properties["totalTime"]

        return {
            # 이동수단
            "mode": "transit",

            # BUS / SUBWAY / BUS_AND_SUBWAY 등
            "route_type":
                properties["type"],

            # 전체 이동거리(m)
            "distance_m":
                properties["totalDistance"],

            # 전체 이동시간(초)
            "duration_sec": total_time,

            # 계산 및 화면 표시용 이동시간(분)
            "duration_min": round(total_time / 60),

            # 총 환승 횟수
            "transfers":
                properties["transfers"],

            # 총 교통요금
            "fare":
                properties.get("fare", {}).get("value"),

            # 도보 / 버스 / 지하철 세부 경로
            "paths": paths
        }

    except (KeyError, IndexError, TypeError, ValueError):
        return None


# 7. 도보 이동시간 계산
def get_walking(
    start_x,
    start_y,
    end_x,
    end_y
):
    """
    두 좌표 사이의 직선거리를 기준으로
    도보 이동시간을 추정한다.

    대중교통 경로가 없는 근거리 후보를
    처리하기 위한 fallback 용도이다.
    """

    from math import radians, sin, cos, sqrt, atan2

    # 위도 / 경도를 라디안으로 변환
    lat1 = radians(float(start_y))
    lon1 = radians(float(start_x))
    lat2 = radians(float(end_y))
    lon2 = radians(float(end_x))

    # 지구 반지름(km)
    earth_radius = 6371.0

    # 두 좌표의 차이
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Haversine 공식으로 직선거리 계산
    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    distance_km = earth_radius * c

    # 실제 보행거리는 직선거리보다 길기 때문에
    # 보정계수 1.2를 적용한다.
    walking_distance_km = distance_km * 1.2

    # 평균 보행속도 4.5 km/h 기준
    walking_minutes = (
        walking_distance_km / 4.5
    ) * 60

    return {
        "mode": "walk",

        "distance_km": round(
            walking_distance_km,
            2
        ),

        "duration_min": max(
            1,
            round(walking_minutes)
        )
    }


# 8. 근거리 여부 확인
def is_nearby(
    start_x,
    start_y,
    end_x,
    end_y,
    max_distance_km=ACTUAL_ROUTE_WALK_THRESHOLD_KM
):
    """
    두 좌표의 직선거리를 계산하여
    도보 fallback이 가능한 근거리인지 판단한다.

    기본 기준:
    - 직선거리 1.5km 이하 → 근거리
    - 직선거리 1.5km 초과 → 근거리 아님
    """

    from math import radians, sin, cos, sqrt, atan2

    lat1 = radians(float(start_y))
    lon1 = radians(float(start_x))
    lat2 = radians(float(end_y))
    lon2 = radians(float(end_x))

    earth_radius = 6371.0

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    distance_km = earth_radius * c

    return distance_km <= max_distance_km


# 9. 자동차 이동시간 계산
def get_driving(
    start_x,
    start_y,
    end_x,
    end_y
):
    """
    Kakao Mobility 자동차 길찾기 API를 이용해
    두 좌표 사이의 자동차 이동시간을 계산한다.

    다른 이동수단과 동일하게 추천 계산에서 사용하는
    duration_min 필드를 포함한 공통 형식으로 반환한다.

    API 호출 또는 경로 조회에 실패하면 None을 반환한다.
    """

    url = (
        "https://apis-navi.kakaomobility.com/"
        "v1/directions"
    )

    params = {
        "origin": f"{start_x},{start_y}",
        "destination": f"{end_x},{end_y}",
        "priority": "TIME",
        "summary": "true",
    }

    try:
        response = requests.get(
            url,
            headers=kakao_headers(),
            params=params,
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError):
        return None

    routes = data.get("routes", [])

    if not routes:
        return None

    route = routes[0]
    result_code = route.get("result_code")

    # 출발지와 목적지가 5m 이내인 경우 이동시간을 0분으로 처리한다.
    if result_code == 104:
        return {
            "mode": "car",
            "distance_m": 0,
            "duration_sec": 0,
            "duration_min": 0,
            "toll": 0,
            "taxi_fare": 0,
        }

    if result_code != 0:
        return None

    summary = route.get("summary")

    if not summary:
        return None

    duration_sec = summary.get("duration")
    distance_m = summary.get("distance")

    if duration_sec is None or distance_m is None:
        return None

    fare = summary.get("fare") or {}

    return {
        "mode": "car",
        "distance_m": distance_m,
        "duration_sec": duration_sec,
        "duration_min": max(
            1,
            round(duration_sec / 60)
        ),
        "toll": fare.get("toll"),
        "taxi_fare": fare.get("taxi"),
    }


# 10. 이동수단에 따른 이동시간 계산
def get_travel(
    start_x,
    start_y,
    end_x,
    end_y,
    transport_mode="auto"
):
    """
    사용자가 선택한 이동수단에 따라 이동시간을 계산한다.

    auto:
    - 1.5km 이내 → 도보
    - 1.5km 초과 → 대중교통

    public_transit:
    - 대중교통

    walk:
    - 도보

    car:
    - 자동차

    현재 지원하지 않는 이동수단이 들어오면 None을 반환한다.
    """

    # 10-1. 도보를 직접 선택한 경우
    if transport_mode == "walk":

        return get_walking(
            start_x,
            start_y,
            end_x,
            end_y
        )

    # 10-2. 대중교통을 직접 선택한 경우
    if transport_mode == "public_transit":
        transit = get_transit(
            start_x,
            start_y,
            end_x,
            end_y
        )

        if transit is not None:
            return transit

        if is_nearby(
            start_x,
            start_y,
            end_x,
            end_y,
            max_distance_km=(
                PUBLIC_TRANSIT_WALK_FALLBACK_MAX_DISTANCE_M / 1000
            ),
        ):
            return get_walking(
                start_x,
                start_y,
                end_x,
                end_y,
            )

        return None

    # 10-3. 자동차를 직접 선택한 경우
    if transport_mode == "car":

        return get_driving(
            start_x,
            start_y,
            end_x,
            end_y
        )

    # 10-4. auto인 경우 거리에 따라 이동수단 자동 선택
    if transport_mode == "auto":

        # 가까운 거리라면 도보 사용
        if is_nearby(
            start_x,
            start_y,
            end_x,
            end_y
        ):

            return get_walking(
                start_x,
                start_y,
                end_x,
                end_y
            )

        # 근거리가 아니라면 대중교통 사용
        return get_transit(
            start_x,
            start_y,
            end_x,
            end_y
        )

    # 아직 지원하지 않는 이동수단
    return None
