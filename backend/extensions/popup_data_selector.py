import logging
import re

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from popup_service import PopupDataError, load_popup_places


logger = logging.getLogger("uvicorn.error")

BACKEND_DIR = Path(__file__).resolve().parent.parent
POPUP_DATA_DIR = BACKEND_DIR / "popup_data"
KST = timezone(timedelta(hours=9))
POPUP_FILE_PATTERN = re.compile(
    r"^(?P<date>\d{8})_popup_places\.json$"
)

SALES_FOCUSED_TITLE_PATTERN = re.compile(
    r"선물\s*(?:세트|셋트)|"
    r"gift\s*(?:pop\s*[-–—]?\s*up|popup)|"
    r"추석[^\n]*(?:gift|선물)|"
    r"무이자\s*할부|"
    r"(?:할인|특가|프로모션)\s*(?:pop\s*[-–—]?\s*up|popup|행사)?\s*$",
    re.I,
)
SALES_FOCUSED_DETAIL_PATTERNS = (
    re.compile(r"\d+(?:\s*[~-]\s*\d+)?\s*%\s*(?:off|할인)", re.I),
    re.compile(r"단독\s*특가|행사\s*상품|최대\s*\d+\s*%", re.I),
    re.compile(r"구매\s*(?:시|고객|금액)|금액\s*이상\s*구매", re.I),
    re.compile(r"(?:사은품|상품)\s*증정|할인\s*혜택", re.I),
)
EXPERIENCE_PATTERN = re.compile(
    r"체험|워크숍|워크샵|클래스|포토\s*존|게임|미션|"
    r"시식|시음|시향|커스텀|각인|만들기|참여|테스트|"
    r"전시|사인회|포토\s*타임|쇼룸|"
    r"직접\s*(?:만나|보|입|써|사용|경험|체험|맛보|느껴|확인)",
    re.I,
)
SPECIAL_PRODUCT_PATTERN = re.compile(
    r"한정|굿즈|콜라보|리미티드|limited|exclusive|"
    r"스페셜\s*에디션|신제품|신메뉴|최초|팝업에서만|"
    r"오직[^\n]{0,20}팝업",
    re.I,
)
BENEFIT_ONLY_TITLE_PATTERN = re.compile(
    r"(?:카드|nh농협|우리카드)[^\n]*(?:무이자|할부)|"
    r"(?:쿠폰|바우처|voucher|쇼핑\s*찬스)\s*[!！]?\s*$",
    re.I,
)


def _popup_search_text(place):
    values = [
        place.get("name"),
        place.get("description"),
        place.get("venue_name"),
        place.get("category_detail"),
        *(place.get("tags") or []),
        *(place.get("popup_categories") or []),
    ]
    return " ".join(str(value) for value in values if value)


def is_sales_centered_without_experience(place):
    """체험·한정 가치 없이 할인이나 선물 판매가 중심인 팝업인지 판정한다."""

    if not isinstance(place, dict):
        return False

    name = str(place.get("name") or "")
    description = str(place.get("description") or "")
    search_text = _popup_search_text(place)

    if EXPERIENCE_PATTERN.search(search_text):
        return False

    if SPECIAL_PRODUCT_PATTERN.search(search_text):
        return False

    if BENEFIT_ONLY_TITLE_PATTERN.search(name):
        return True

    if SALES_FOCUSED_TITLE_PATTERN.search(name):
        return True

    sales_detail_signal_count = sum(
        bool(pattern.search(description))
        for pattern in SALES_FOCUSED_DETAIL_PATTERNS
    )
    return sales_detail_signal_count >= 2


def filter_recommendable_popup_places(places):
    """판매 중심 팝업은 원본에서 삭제하지 않고 추천 후보에서만 제외한다."""

    return [
        place
        for place in places
        if not is_sales_centered_without_experience(place)
    ]


def _as_reference_date(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(KST)
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    return None


def _file_date(path):
    match = POPUP_FILE_PATTERN.fullmatch(path.name)
    if match is None:
        return None

    try:
        return datetime.strptime(match.group("date"), "%Y%m%d").date()
    except ValueError:
        return None


def _existing_dated_files(data_dir):
    try:
        files = [
            (file_date, path)
            for path in data_dir.iterdir()
            if path.is_file()
            and (file_date := _file_date(path)) is not None
        ]
    except OSError as error:
        logger.warning(
            "[popup-data-directory-error] directory=%s error=%s",
            data_dir,
            error,
        )
        return []

    return [
        path
        for _, path in sorted(files, key=lambda item: item[0], reverse=True)
    ]


def get_popup_data_candidates(
    reference_date=None,
    *,
    now=None,
    data_dir=None,
):
    """요청 기준일, KST 오늘, 최신 파일 순으로 후보를 반환한다."""

    data_dir = Path(data_dir) if data_dir is not None else POPUP_DATA_DIR
    reference_date = _as_reference_date(reference_date)

    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    candidate_dates = []
    if reference_date is not None:
        candidate_dates.append(reference_date)
    if now.date() not in candidate_dates:
        candidate_dates.append(now.date())

    candidates = [
        data_dir / f"{candidate_date:%Y%m%d}_popup_places.json"
        for candidate_date in candidate_dates
    ]
    seen = {path.resolve() for path in candidates}

    for path in _existing_dated_files(data_dir):
        resolved_path = path.resolve()
        if resolved_path not in seen:
            candidates.append(path)
            seen.add(resolved_path)

    return candidates


def load_popup_places_for_date(
    reference_date=None,
    *,
    now=None,
    data_dir=None,
    load_popup_places_fn=load_popup_places,
):
    """우선순위에 맞는 첫 정상 파일을 읽고 없으면 빈 목록을 반환한다."""

    candidates = get_popup_data_candidates(
        reference_date,
        now=now,
        data_dir=data_dir,
    )

    for path in candidates:
        try:
            places = load_popup_places_fn(path)
        except PopupDataError as error:
            logger.warning(
                "[popup-data-skip] file=%s error=%s",
                path.name,
                error,
            )
            continue

        if not places:
            logger.warning("[popup-data-empty] file=%s", path.name)
            continue

        recommendable_places = filter_recommendable_popup_places(places)
        excluded_sales_count = len(places) - len(recommendable_places)
        selected_date = _file_date(path)
        logger.info(
            "[popup-data-selected] date=%s file=%s count=%d "
            "excluded_sales=%d raw_count=%d",
            selected_date.isoformat() if selected_date is not None else "unknown",
            path.name,
            len(recommendable_places),
            excluded_sales_count,
            len(places),
        )
        return recommendable_places

    logger.warning(
        "[popup-data-unavailable] reference_date=%s directory=%s; "
        "popup recommendations are disabled",
        _as_reference_date(reference_date),
        Path(data_dir) if data_dir is not None else POPUP_DATA_DIR,
    )
    return []
