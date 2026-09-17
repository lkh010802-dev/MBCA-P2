import pandas as pd


# 1. 서울 121개 POI 후보 불러오기
def load_poi_candidates():
    """
    서울 실시간 도시데이터 기준 121개 POI의
    이름, 카테고리, 좌표 정보를 불러와 후보지역을 하나씩 처리하기 편하도록
    딕셔너리 리스트 형태로 변환한다.
    """

    # POI 좌표 데이터 불러오기
    df = pd.read_csv(
        "data/poi121_coordinates.csv"
    )

    # 추천 계산에 필요한 컬럼만 선택
    candidates = df[
        [
            "AREA_CD",
            "AREA_NM",
            "CATEGORY",
            "longitude",
            "latitude"
        ]
    ].to_dict(
        orient="records"
    )

    return candidates