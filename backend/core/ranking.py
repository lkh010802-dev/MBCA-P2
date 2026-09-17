def convert_congestion_to_score(
    congestion_level: str
):
    """
    서울시 혼잡도 등급을
    추천 계산용 1~5점으로 변환한다.
    """

    score_map = {
        "여유": 5,
        "보통": 4,
        "약간 붐빔": 2,
        "붐빔": 1,
    }

    return score_map.get(
        congestion_level,
        3
    )


def convert_travel_ratio_to_score(
    travel_ratio: float
):
    """
    전체 사용 가능 시간 중 이동시간이 차지하는 비율을
    추천 계산용 1~5점으로 변환한다.
    이동 비율이 낮을수록 높은 점수를 준다.

    0%  -> 5점
    30% -> 1점
    """

    score = 5 - (travel_ratio / 0.30) * 4

    return max(1, score)

def calculate_final_score(
    activity_score: float,
    congestion_score: float,
    travel_score: float,
    has_activity: bool = True
):
    """
    활동 적합도, 혼잡도, 이동 부담 점수를
    가중합하여 최종 추천 점수를 계산한다.

    활동이 지정된 경우:
    - 활동 적합도: 50%
    - 이동 부담: 30%
    - 혼잡도: 20%

    활동이 지정되지 않은 경우:
    - 이동 부담: 60%
    - 혼잡도: 40%
    """

    if has_activity:
        final_score = (
            activity_score * 0.5
            + travel_score * 0.3
            + congestion_score * 0.2
        )

    else:
        final_score = (
            travel_score * 0.6
            + congestion_score * 0.4
        )

    return final_score

def convert_travel_minutes_to_score(
    travel_minutes: int
):
    """
    종료시간이 없는 경우,
    실제 이동시간 자체를 기준으로 1~5점으로 변환한다.

    0분  -> 5점
    30분 -> 3점
    60분 -> 1점
    60분 초과 -> 최소 1점
    """

    score = 5 - (travel_minutes / 60) * 4

    return max(1, score)