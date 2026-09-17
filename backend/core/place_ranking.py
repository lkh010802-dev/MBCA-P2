def calculate_distance_score(
    distance_m: int | None,
    max_distance_m: int = 2000,
):
    """
    장소까지의 거리를 0~100점으로 변환한다.

    가까울수록 높은 점수를 받는다.

    예:
    0m    → 100점
    1000m → 50점
    2000m → 0점

    최대 거리보다 먼 경우에도 0점으로 처리한다.
    """

    if distance_m is None:
        return 0

    score = (
        1
        - min(distance_m, max_distance_m)
        / max_distance_m
    ) * 100

    return round(score, 2)


def add_place_ranking_scores(
    places: list[dict],
    space_preference: str | None = None,
):
    """
    실제 장소 후보에 랭킹 계산용 점수를 추가한다.

    거리 점수와 사용자의 공간 선호 가점을 계산한다.
    """

    scored_places = []

    for place in places:
        scored_place = place.copy()

        scored_place["place_score"] = (
            calculate_place_score(
                place,
                space_preference,
            )
        )

        scored_place["distance_score"] = (
            calculate_distance_score(
                place.get("distance_m")
            )
        )

        scored_places.append(
            scored_place
        )

    return scored_places

def sort_places_by_score(
    places: list[dict],
):
    """
    장소 후보를 최종 장소 점수가 높은 순서대로 정렬한다.
    """

    return sorted(
        places,
        key=lambda place: place.get(
            "place_score",
            0
        ),
        reverse=True
    )

def calculate_place_score(
    place: dict,
    space_preference: str | None = None,
):
    """
    실제 장소의 최종 추천 점수를 계산한다.

    거리 점수에 신뢰 가능한 공간 선호 가점만 합산한다.
    """

    distance_score = calculate_distance_score(
        place.get("distance_m")
    )

    if (
        space_preference not in {"indoor", "outdoor"}
        or place.get("distance_m") is None
    ):
        return round(distance_score, 2)

    space_type = place.get("space_type")
    confidence = place.get("space_type_confidence")

    if space_type == "mixed":
        space_bonus = 0.5
    elif space_type != space_preference:
        space_bonus = 0
    elif confidence == "high":
        space_bonus = 2.0
    elif confidence == "medium":
        space_bonus = 1.0
    else:
        space_bonus = 0

    return round(distance_score + space_bonus, 2)
