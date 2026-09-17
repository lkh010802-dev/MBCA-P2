from functools import lru_cache
from pathlib import Path

import pandas as pd


# 1. 서울시 상권 업종명을 우리 서비스의 활동 카테고리로 묶음
# 예:
# 한식음식점, 중식음식점 ... → food
# 커피-음료, 제과점          → cafe
# 호프-간이주점              → drink
#
# 현재는 food / cafe / drink / entertainment만 사용한다.
# walk, culture 등은 점포 데이터보다는 POI 자체 특성을 이용해
# 별도로 처리할 예정이다.
ACTIVITY_BUSINESS_TYPES = {
    "food": [
        "한식음식점",
        "중식음식점",
        "일식음식점",
        "양식음식점",
        "분식전문점",
        "치킨전문점",
        "패스트푸드점",
    ],

    "cafe": [
        "커피-음료",
        "제과점",
    ],

    "drink": [
        "호프-간이주점",
    ],

    "entertainment": [
        "PC방",
        "노래방",
        "당구장",
        "볼링장",
        "전자게임장",
        "기타오락장",
        "DVD방",
    ],
}


# 2. 점포 데이터 불러오기
def load_store_data(file_path):
    """
    서울시 상권분석서비스 점포-행정동 CSV를 불러온다.

    해당 CSV 파일은 cp949 인코딩을 사용한다.
    """
    return pd.read_csv(
        file_path,
        encoding="cp949"
    )


# 3. 가장 최신 분기 데이터만 선택
def filter_latest_quarter(df):
    """
    2025년 데이터 안에서 가장 최근 분기만 남긴다.

    예:
    20251
    20252
    20253
    20254

    중 가장 큰 값을 사용한다.
    """
    latest_quarter = df["기준_년분기_코드"].max()

    return df[
        df["기준_년분기_코드"] == latest_quarter
    ].copy()


# 4. 행정동별 활동 관련 점포 수 계산
def aggregate_activity_store_counts(df):
    """
    행정동별로 food / cafe / drink / entertainment에
    해당하는 점포 수를 각각 계산한다.

    반환값은 activity별 DataFrame 리스트다.

    예:
    food 결과
    행정동 | food_count

    cafe 결과
    행정동 | cafe_count
    """

    results = []

    # activity마다 지정된 업종 목록을 하나씩 처리
    for activity, business_types in ACTIVITY_BUSINESS_TYPES.items():

        # 현재 activity에 해당하는 업종만 선택
        activity_df = df[
            df["서비스_업종_코드_명"].isin(
                business_types
            )
        ]

        # 같은 행정동에 있는 해당 업종의 점포 수를 모두 합산
        grouped = (
            activity_df
            .groupby(
                [
                    "행정동_코드",
                    "행정동_코드_명"
                ],
                as_index=False
            )["점포_수"]
            .sum()
        )

        # 점포_수 컬럼 이름을 activity에 맞게 변경
        # 예: food_count, cafe_count
        grouped = grouped.rename(
            columns={
                "점포_수": f"{activity}_count"
            }
        )

        results.append(grouped)

    return results


# 5. activity별 결과를 하나의 행정동 표로 합치기
def merge_activity_store_counts(activity_results):
    """
    food / cafe / drink / entertainment로 따로 계산된 결과를
    하나의 DataFrame으로 합친다.

    최종 형태 예:

    행정동
    food_count
    cafe_count
    drink_count
    entertainment_count
    """

    merged = activity_results[0]

    # 첫 번째 결과에 나머지 activity 결과를 차례대로 연결
    for result in activity_results[1:]:

        merged = merged.merge(
            result,
            on=[
                "행정동_코드",
                "행정동_코드_명"
            ],
            how="outer"
        )

    # *_count 형태의 컬럼만 찾음
    count_columns = [
        column
        for column in merged.columns
        if column.endswith("_count")
    ]

    # 해당 activity 점포가 없는 행정동은 NaN 대신 0으로 처리
    merged[count_columns] = (
        merged[count_columns]
        .fillna(0)
    )

    return merged


# 6. POI ↔ 행정동 매핑 데이터 불러오기
def load_poi_mapping(file_path):
    """
    서울시 주요 121개 POI와 행정동의 매핑 데이터를 불러온다.

    하나의 POI가 여러 행정동에 걸쳐 있을 수 있으며,
    poi_share 컬럼에는 각 행정동과 겹치는 비율이 들어 있다.
    """
    return pd.read_csv(file_path)


# 7. 행정동 점포 데이터를 POI 단위로 변환
def aggregate_activity_counts_by_poi(
    mapping_df,
    activity_df
):
    """
    행정동별 활동 점포 수를 121개 POI 단위로 변환한다.

    POI가 여러 행정동에 걸쳐 있을 수 있으므로
    poi_share를 이용해 각 행정동의 점포 수를 가중해서 합산한다.

    예:
    어떤 POI가

    A동 60%
    B동 40%

    에 걸쳐 있고,

    A동 cafe_count = 300
    B동 cafe_count = 200

    이라면

    POI cafe_count
    = 300 * 0.6 + 200 * 0.4
    = 260

    으로 계산한다.

    주의:
    이 값은 POI 내부의 실제 점포 수를 정확히 의미하는 것이 아니라,
    활동 적합도를 비교하기 위한 추정값이다.
    """

    # POI 매핑 데이터와 점포 데이터를 행정동 기준으로 연결
    # 두 데이터가 서로 다른 행정동 코드 체계를 사용하고 있어서
    # 행정동 코드가 아니라 행정동 이름으로 연결한다.
    merged = mapping_df.merge(
        activity_df,
        left_on="ADM_NM",
        right_on="행정동_코드_명",
        how="left"
    )

    # food_count, cafe_count 등 *_count 컬럼 찾기
    count_columns = [
        column
        for column in activity_df.columns
        if column.endswith("_count")
    ]

    # 연결된 점포 데이터가 없는 경우 0으로 처리
    merged[count_columns] = (
        merged[count_columns]
        .fillna(0)
    )

    # 행정동 점포 수 × POI와 겹치는 비율
    for column in count_columns:

        merged[f"weighted_{column}"] = (
            merged[column]
            * merged["poi_share"]
        )

    weighted_columns = [
        f"weighted_{column}"
        for column in count_columns
    ]

    # 같은 POI에 연결된 행정동 결과를 모두 합산
    poi_activity_df = (
        merged
        .groupby(
            [
                "AREA_CD",
                "AREA_NM",
                "CATEGORY"
            ],
            as_index=False
        )[weighted_columns]
        .sum()
    )

    # weighted_food_count 같은 이름을 다시 food_count로 정리
    poi_activity_df = poi_activity_df.rename(
        columns={
            f"weighted_{column}": column
            for column in count_columns
        }
    )

    return poi_activity_df


# 8. POI별 활동 관련 점포 수를 1~5점으로 변환
def convert_counts_to_scores(poi_activity_df):
    """
    POI별 food / cafe / drink / entertainment 값을
    1~5점 상대점수로 변환한다.

    121개 POI를 서로 비교해서
    해당 activity 관련 점포가 많은 지역일수록 높은 점수를 준다.

    현재 점수 의미:

    1점 → 121개 중 상대적으로 적음
    2점 → 적은 편
    3점 → 중간
    4점 → 많은 편
    5점 → 매우 많은 편

    현재는 qcut을 이용해 5개 구간으로 나눈다.

    이 점수는 절대적인 지역 평가가 아니라
    Ranking용 상대 비교 점수다.
    """

    score_df = poi_activity_df.copy()

    count_columns = [
        column
        for column in score_df.columns
        if column.endswith("_count")
    ]

    for column in count_columns:

        # 예:
        # cafe_count → cafe_score
        score_column = column.replace(
            "_count",
            "_score"
        )

        # 점포 수 순위를 기준으로 121개 POI를 5개 구간으로 나눔
        score_df[score_column] = pd.qcut(
            score_df[column].rank(
                method="first"
            ),
            q=5,
            labels=[
                1,
                2,
                3,
                4,
                5
            ]
        ).astype(int)

    return score_df

# 9. POI CATEGORY를 이용해 walk / culture / shopping 점수 생성
def add_category_activity_scores(score_df):
    """
    서울시 121개 POI의 CATEGORY를 이용해
    walk / culture / shopping 활동 적합도를 1~5점으로 부여한다.

    점포 수로 판단하기 어려운 활동이므로
    POI 자체 성격을 기준으로 하는 MVP용 규칙 점수다.
    """

    category_scores = {
        "공원": {
            "walk_score": 5,
            "culture_score": 2,
            "shopping_score": 1,
        },

        "고궁·문화유산": {
            "walk_score": 4,
            "culture_score": 5,
            "shopping_score": 2,
        },

        "관광특구": {
            "walk_score": 3,
            "culture_score": 3,
            "shopping_score": 4,
        },

        "발달상권": {
            "walk_score": 2,
            "culture_score": 1,
            "shopping_score": 5,
        },

        "인구밀집지역": {
            "walk_score": 1,
            "culture_score": 1,
            "shopping_score": 3,
        },
    }

    result_df = score_df.copy()

    result_df["walk_score"] = (
        result_df["CATEGORY"]
        .map(
            lambda category:
            category_scores.get(
                category,
                {}
            ).get("walk_score", 1)
        )
    )

    result_df["culture_score"] = (
        result_df["CATEGORY"]
        .map(
            lambda category:
            category_scores.get(
                category,
                {}
            ).get("culture_score", 1)
        )
    )

    result_df["shopping_score"] = (
        result_df["CATEGORY"]
        .map(
            lambda category:
            category_scores.get(
                category,
                {}
            ).get("shopping_score", 1)
        )
    )

    return result_df


@lru_cache(maxsize=4)
def _load_poi_activity_scores_cached(
    store_file: str,
    mapping_file: str,
):
    # 점포 데이터 로드
    store_df = load_store_data(store_file)

    # 최신 분기 선택
    latest_df = filter_latest_quarter(store_df)

    # 행정동별 활동 점포 수 계산
    activity_results = aggregate_activity_store_counts(
        latest_df
    )

    # 활동별 결과를 하나로 합침
    merged_activity_df = merge_activity_store_counts(
        activity_results
    )

    # POI ↔ 행정동 매핑 로드
    mapping_df = load_poi_mapping(
        mapping_file
    )

    # 행정동 데이터를 POI 단위로 변환
    poi_activity_df = aggregate_activity_counts_by_poi(
        mapping_df,
        merged_activity_df
    )

    # 점포 수를 1~5점으로 변환
    poi_score_df = convert_counts_to_scores(
        poi_activity_df
    )

    # POI CATEGORY 기반 활동 점수 추가
    poi_score_df = add_category_activity_scores(
        poi_score_df
    )

    return poi_score_df


def load_poi_activity_scores(
    store_file="data/서울시 상권분석서비스(점포-행정동)_2025년.csv",
    mapping_file="data/poi121_매핑결과.csv"
):
    """
    점포 데이터와 POI-행정동 매핑 데이터를 이용해
    121개 POI의 활동 적합도 점수를 생성한다.

    main.py 등 다른 파일에서는 이 함수 하나만 호출하면
    food / cafe / drink / entertainment 점수를 사용할 수 있다.
    """

    cached_scores = _load_poi_activity_scores_cached(
        str(Path(store_file).resolve()),
        str(Path(mapping_file).resolve()),
    )
    return cached_scores.copy(deep=True)
# 테스트 실행
# activity_score.py를 직접 실행했을 때만 아래 코드가 실행된다.
# 다른 파일에서 import할 때는 실행되지 않는다.
if __name__ == "__main__":

    # 사용 데이터 파일
    store_file = (
        "data/서울시 상권분석서비스(점포-행정동)_2025년.csv"
    )

    mapping_file = (
        "data/poi121_매핑결과.csv"
    )

    # 1. 서울시 점포 데이터 불러오기
    store_df = load_store_data(
        store_file
    )

    # 2. 가장 최근 분기만 선택
    latest_df = filter_latest_quarter(
        store_df
    )

    # 3. 행정동별 활동 관련 점포 수 계산
    activity_results = (
        aggregate_activity_store_counts(
            latest_df
        )
    )

    # 4. 활동별 결과를 하나의 행정동 표로 합치기
    merged_activity_df = (
        merge_activity_store_counts(
            activity_results
        )
    )

    # 5. POI ↔ 행정동 매핑 데이터 불러오기
    mapping_df = load_poi_mapping(
        mapping_file
    )

    # 6. 행정동 데이터를 121개 POI 단위로 변환
    poi_activity_df = (
        aggregate_activity_counts_by_poi(
            mapping_df,
            merged_activity_df
        )
    )

    # 7. 각 POI의 활동 적합도를 1~5점으로 변환
    poi_score_df = convert_counts_to_scores(
        poi_activity_df
    )

    # 결과 확인
    print(
        poi_score_df[
            [
                "AREA_CD",
                "AREA_NM",
                "CATEGORY",
                "food_score",
                "cafe_score",
                "drink_score",
                "entertainment_score",
            ]
        ].head(30)
    )

