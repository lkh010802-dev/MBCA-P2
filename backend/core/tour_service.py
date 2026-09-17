import os
import math
from datetime import date

import requests
from dotenv import load_dotenv


# .env 파일의 환경변수를 불러온다.
load_dotenv()


# 한국관광공사 API 서비스 키
TOUR_API_KEY = os.getenv("TOUR_API_KEY")


# 기초지자체 중심 관광지 API 주소
HUB_PLACE_API_URL = (
    "https://apis.data.go.kr/"
    "B551011/"
    "LocgoHubTarService1/"
    "areaBasedList1"
)
TOUR_BASE_YM_LOOKBACK_MONTHS = 6

# 서울 25개 자치구 → TourAPI 시군구 코드
SEOUL_TOUR_SIGUNGU_CODES = {
    "종로구": "11110",
    "중구": "11140",
    "용산구": "11170",
    "성동구": "11200",
    "광진구": "11215",
    "동대문구": "11230",
    "중랑구": "11260",
    "성북구": "11290",
    "강북구": "11305",
    "도봉구": "11320",
    "노원구": "11350",
    "은평구": "11380",
    "서대문구": "11410",
    "마포구": "11440",
    "양천구": "11470",
    "강서구": "11500",
    "구로구": "11530",
    "금천구": "11545",
    "영등포구": "11560",
    "동작구": "11590",
    "관악구": "11620",
    "서초구": "11650",
    "강남구": "11680",
    "송파구": "11710",
    "강동구": "11740",
}


# 행정구 이름 → TourAPI 시군구 코드 변환
def get_tour_sigungu_code(
    sigungu_name: str,
):
    """
    Kakao 좌표 → 행정구역 조회에서 얻은
    서울 자치구 이름을 TourAPI의 signguCd로 변환한다.

    예:
    마포구 → 11440
    강남구 → 11680

    지원하지 않는 지역은 None을 반환한다.
    """

    return SEOUL_TOUR_SIGUNGU_CODES.get(
        sigungu_name
    )

def calculate_distance_km(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
):
    """
    두 좌표 사이의 직선거리를 km 단위로 계산한다.
    """

    earth_radius_km = 6371.0

    lat1 = math.radians(latitude1)
    lon1 = math.radians(longitude1)
    lat2 = math.radians(latitude2)
    lon2 = math.radians(longitude2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return earth_radius_km * c

def add_distance_to_places(
    places: list[dict],
    poi_latitude: float,
    poi_longitude: float,
):
    """
    관광지 후보 각각에 추천 POI로부터의 직선거리를 추가한다.
    """

    for place in places:
        place_latitude = float(place["mapY"])
        place_longitude = float(place["mapX"])

        distance_km = calculate_distance_km(
            latitude1=poi_latitude,
            longitude1=poi_longitude,
            latitude2=place_latitude,
            longitude2=place_longitude,
        )

        place["poi_distance_km"] = round(distance_km, 2)

    return places

def filter_places_by_distance(
    places: list[dict],
    max_distance_km: float = 2.0,
):
    """
    추천 POI로부터 일정 거리 안에 있는 장소만 남긴다.
    """

    filtered_places = []

    for place in places:
        distance_km = place.get("poi_distance_km")

        if distance_km is None:
            continue

        if distance_km <= max_distance_km:
            filtered_places.append(place)

    return filtered_places


def get_hub_places(
    gu_code: str,
    base_ym: str,
    num_rows: int = 100,
):
    params = {
        "serviceKey": TOUR_API_KEY,
        "MobileOS": "ETC",
        "MobileApp": "KOALA",
        "_type": "json",
        "numOfRows": num_rows,
        "pageNo": 1,
        "areaCd": "11",
        "signguCd": gu_code,
        "baseYm": base_ym,
    }

    response = requests.get(
        HUB_PLACE_API_URL,
        params=params,
        timeout=10,
    )



    response.raise_for_status()

    data = response.json()

    header = data["response"]["header"]

    if header["resultCode"] not in ("0000", "00"):
        raise RuntimeError(
            f'관광 API 오류: {header["resultMsg"]}'
        )

    body = data["response"]["body"]
    items_container = body.get("items")

    if not isinstance(items_container, dict):
        return []

    items = items_container.get("item", [])

    # 장소가 1개만 오는 경우 dict 형태일 수 있으므로 list로 통일한다.
    if isinstance(items, dict):
        items = [items]

    return items


def get_latest_hub_places(
    gu_code: str,
    reference_date: date | None = None,
    lookback_months: int = TOUR_BASE_YM_LOOKBACK_MONTHS,
):
    """현재월부터 제한된 기간만 역순으로 조회해 최신 공개 데이터를 반환한다."""

    current_date = reference_date or date.today()
    current_month_index = (
        current_date.year * 12
        + current_date.month
        - 1
    )

    for month_offset in range(lookback_months):
        year, zero_based_month = divmod(
            current_month_index - month_offset,
            12,
        )
        base_ym = f"{year}{zero_based_month + 1:02d}"
        places = get_hub_places(
            gu_code=gu_code,
            base_ym=base_ym,
        )

        if places:
            return places

    return []

