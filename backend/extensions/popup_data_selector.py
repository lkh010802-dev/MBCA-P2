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

        selected_date = _file_date(path)
        logger.info(
            "[popup-data-selected] date=%s file=%s count=%d",
            selected_date.isoformat() if selected_date is not None else "unknown",
            path.name,
            len(places),
        )
        return places

    logger.warning(
        "[popup-data-unavailable] reference_date=%s directory=%s; "
        "popup recommendations are disabled",
        _as_reference_date(reference_date),
        Path(data_dir) if data_dir is not None else POPUP_DATA_DIR,
    )
    return []
