import re


UNKNOWN_SPACE = {
    "space_type": "unknown",
    "space_type_confidence": "unknown",
    "space_type_basis": "unknown",
}

INDOOR_CATEGORY_TOKENS = {
    "영화관",
    "극장",
    "박물관",
    "미술관",
    "전시관",
    "전시장",
    "갤러리",
    "백화점",
    "쇼핑몰",
    "호텔",
}
OUTDOOR_CATEGORY_TOKENS = {
    "공원",
    "산",
    "둘레길",
    "도보여행",
    "숲",
    "수목원",
    "식물원",
    "호수",
    "저수지",
}

INDOOR_VENUE_KEYWORDS = (
    "영화관",
    "극장",
    "박물관",
    "미술관",
    "전시관",
    "전시장",
    "갤러리",
    "백화점",
    "쇼핑몰",
    "호텔",
)
OUTDOOR_VENUE_KEYWORDS = (
    "공원",
    "둘레길",
    "도보여행",
    "수목원",
    "식물원",
    "호수",
    "저수지",
)

MIXED_PATTERNS = (
    re.compile(r"실내외"),
    re.compile(r"실내\s*(?:및|·|/)\s*야외(?:\s*복합)?"),
    re.compile(r"야외\s*(?:및|·|/)\s*실내(?:\s*복합)?"),
)
INDOOR_EXPLICIT_PATTERN = re.compile(r"실내\s*(?:팝업|행사|공간)")
OUTDOOR_EXPLICIT_PATTERN = re.compile(r"야외\s*(?:광장|공간|무대|행사)")


def _metadata(space_type: str, confidence: str, basis: str):
    return {
        "space_type": space_type,
        "space_type_confidence": confidence,
        "space_type_basis": basis,
    }


def _text_values(place: dict, fields: tuple[str, ...]):
    values = []

    for field in fields:
        value = place.get(field)

        if isinstance(value, str):
            if value.strip():
                values.append(value.strip())
        elif isinstance(value, (list, tuple, set)):
            values.extend(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )

    return values


def _explicit_result(values: list[str]):
    has_mixed = any(
        pattern.search(value)
        for value in values
        for pattern in MIXED_PATTERNS
    )
    if has_mixed:
        return _metadata("mixed", "high", "explicit")

    has_indoor = any(
        INDOOR_EXPLICIT_PATTERN.search(value)
        for value in values
    )
    has_outdoor = any(
        OUTDOOR_EXPLICIT_PATTERN.search(value)
        for value in values
    )

    if has_indoor and has_outdoor:
        return UNKNOWN_SPACE.copy()
    if has_indoor:
        return _metadata("indoor", "high", "explicit")
    if has_outdoor:
        return _metadata("outdoor", "high", "explicit")

    return None


def _category_tokens(values: list[str]):
    return {
        token.strip()
        for value in values
        for part in value.split(">")
        for token in part.split(",")
        if token.strip()
    }


def _category_result(values: list[str]):
    tokens = _category_tokens(values)
    has_indoor = bool(tokens.intersection(INDOOR_CATEGORY_TOKENS))
    has_outdoor = bool(tokens.intersection(OUTDOOR_CATEGORY_TOKENS))

    if has_indoor and has_outdoor:
        return UNKNOWN_SPACE.copy()
    if has_indoor:
        return _metadata("indoor", "medium", "category")
    if has_outdoor:
        return _metadata("outdoor", "medium", "category")

    return None


def _venue_result(values: list[str], *, allow_outdoor: bool):
    has_indoor = any(
        keyword in value
        for value in values
        for keyword in INDOOR_VENUE_KEYWORDS
    )
    has_outdoor = allow_outdoor and any(
        value.strip().endswith(keyword)
        for value in values
        for keyword in OUTDOOR_VENUE_KEYWORDS
    )

    if has_indoor and has_outdoor:
        return UNKNOWN_SPACE.copy()
    if has_indoor:
        return _metadata("indoor", "medium", "venue")
    if has_outdoor:
        return _metadata("outdoor", "medium", "venue")

    return None


def classify_place_space(place: dict):
    """공통 장소 dict를 보수적으로 분류하며 입력값은 변경하지 않는다."""

    if not isinstance(place, dict):
        return UNKNOWN_SPACE.copy()

    source = place.get("source")

    explicit_fields = {
        "kakao": ("category_detail",),
        "tour": ("category_detail",),
        "seoul_culture": (
            "category_detail",
            "venue_name",
            "address",
            "description",
        ),
        "popup": (
            "popup_categories",
            "tags",
            "venue_name",
            "address",
            "description",
        ),
    }.get(source, ())

    explicit = _explicit_result(
        _text_values(place, explicit_fields)
    )
    if explicit is not None:
        return explicit

    category_fields = {
        "kakao": ("category_detail",),
        "seoul_culture": ("category_detail",),
        "popup": ("category_detail", "popup_categories"),
    }.get(source, ())

    category = _category_result(
        _text_values(place, category_fields)
    )
    if category is not None:
        return category

    if source == "seoul_culture":
        venue = _venue_result(
            _text_values(place, ("venue_name",)),
            allow_outdoor=True,
        )
    elif source == "popup":
        venue = _venue_result(
            _text_values(place, ("venue_name",)),
            allow_outdoor=True,
        )
        if venue is None:
            # 주소 속 '서울숲길' 같은 문자열은 야외 근거로 사용하지 않는다.
            venue = _venue_result(
                _text_values(place, ("address",)),
                allow_outdoor=False,
            )
    else:
        venue = None

    if venue is not None:
        return venue

    return UNKNOWN_SPACE.copy()
