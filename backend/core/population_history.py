"""Seoul living-population collection and local history for D-4 Direct."""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()

SEOUL_POPULATION_SERVICE = "Spop250mLocalResdDong"
SEOUL_OPEN_API_BASE_URL = "http://openapi.seoul.go.kr:8088"
POPULATION_PAGE_SIZE = 1000
EXPECTED_DAILY_ROWS = 427 * 24
EXPECTED_DAILY_DONGS = 427
EXPECTED_DAILY_HOURS = 24
# D-4의 최대 lag(336시간)보다 여유 있게 유지해 일시적인 수집 지연에도 history를 공급한다.
HISTORY_RETENTION_DAYS = 60
REQUIRED_HISTORY_COLUMNS = ["datetime", "행정동코드", "생활인구합계"]
DEFAULT_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "population_history.csv"


class PopulationHistoryError(RuntimeError):
    """The API response or local population history cannot be used safely."""


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.Series(dtype="datetime64[us]"),
            "행정동코드": pd.Series(dtype="string"),
            "생활인구합계": pd.Series(dtype="float64"),
        }
    )


def _normalize_day(value: str | date | pd.Timestamp) -> pd.Timestamp:
    try:
        return pd.Timestamp(value).normalize()
    except (TypeError, ValueError) as exc:
        raise PopulationHistoryError("수집 날짜 형식이 올바르지 않습니다.") from exc


def _population_url(api_key: str, start: int, end: int, day: pd.Timestamp) -> str:
    return (
        f"{SEOUL_OPEN_API_BASE_URL}/{api_key}/json/{SEOUL_POPULATION_SERVICE}"
        f"/{start}/{end}/{day:%Y%m%d}"
    )


def normalize_population_rows(rows: list[dict]) -> pd.DataFrame:
    """Convert Seoul Open API rows to the D-4 provider input schema."""
    if not isinstance(rows, list):
        raise PopulationHistoryError("서울 생활인구 API row 형식이 올바르지 않습니다.")

    frame = pd.DataFrame(rows)
    required = {"YMD", "TT", "H_DNG_CD", "SPOP"}
    missing = required.difference(frame.columns)
    if missing:
        raise PopulationHistoryError(f"서울 생활인구 API 필드가 없습니다: {sorted(missing)}")

    # Open API 필드명을 Provider가 요구하는 datetime/행정동코드/생활인구합계 스키마로 고정한다.
    codes = frame["H_DNG_CD"].astype("string").str.strip()
    hours = pd.to_numeric(frame["TT"], errors="coerce")
    population = pd.to_numeric(frame["SPOP"], errors="coerce")
    datetimes = pd.to_datetime(
        frame["YMD"].astype("string").str.strip()
        + hours.astype("Int64").astype("string").str.zfill(2),
        format="%Y%m%d%H",
        errors="coerce",
    )

    if hours.isna().any() or (~hours.between(0, 23)).any():
        raise PopulationHistoryError("서울 생활인구 API 시간 값이 올바르지 않습니다.")
    if datetimes.isna().any() or codes.isna().any() or (codes == "").any():
        raise PopulationHistoryError("서울 생활인구 API 날짜 또는 행정동 코드가 올바르지 않습니다.")
    if population.isna().any():
        raise PopulationHistoryError("서울 생활인구 API 생활인구 값이 숫자가 아닙니다.")

    return pd.DataFrame(
        {
            "datetime": datetimes,
            "행정동코드": codes.astype("string"),
            "생활인구합계": population.astype("float64"),
        }
    )


def validate_daily_population(frame: pd.DataFrame, day: str | date | pd.Timestamp) -> None:
    """Reject an incomplete or malformed daily API result before persistence."""
    expected_day = _normalize_day(day)
    if list(frame.columns) != REQUIRED_HISTORY_COLUMNS:
        raise PopulationHistoryError("생활인구 history 스키마가 올바르지 않습니다.")
    if frame["datetime"].isna().any() or frame["행정동코드"].isna().any():
        raise PopulationHistoryError("생활인구 history에 null 키가 있습니다.")
    if (frame["행정동코드"] != frame["행정동코드"].astype("string").str.strip()).any():
        raise PopulationHistoryError("생활인구 history 행정동 코드의 공백이 제거되지 않았습니다.")
    if frame["생활인구합계"].isna().any():
        raise PopulationHistoryError("생활인구 history에 null 값이 있습니다.")
    if frame.duplicated(["datetime", "행정동코드"]).any():
        raise PopulationHistoryError("생활인구 history에 중복 시각/행정동 코드가 있습니다.")
    if len(frame) != EXPECTED_DAILY_ROWS:
        raise PopulationHistoryError(f"하루 생활인구 행 수가 불완전합니다: {len(frame)}")
    if frame["행정동코드"].nunique() != EXPECTED_DAILY_DONGS:
        raise PopulationHistoryError("하루 생활인구 행정동 코드 수가 올바르지 않습니다.")
    if frame["datetime"].nunique() != EXPECTED_DAILY_HOURS:
        raise PopulationHistoryError("하루 생활인구 시간 수가 올바르지 않습니다.")
    if not (frame["datetime"].dt.normalize() == expected_day).all():
        raise PopulationHistoryError("수집 날짜와 API 응답 날짜가 일치하지 않습니다.")


def fetch_population_day(
    day: str | date | pd.Timestamp,
    *,
    api_key: str | None = None,
    http_get=requests.get,
) -> pd.DataFrame:
    """Fetch all pages for one Seoul living-population day without persisting it."""
    requested_day = _normalize_day(day)
    api_key = api_key or os.getenv("SEOUL_API_KEY")
    if not api_key:
        raise PopulationHistoryError("SEOUL_API_KEY 환경변수가 필요합니다.")

    rows: list[dict] = []
    start = 1
    total: int | None = None
    while total is None or len(rows) < total:
        end = start + POPULATION_PAGE_SIZE - 1
        try:
            response = http_get(
                _population_url(api_key, start, end, requested_day), timeout=15
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PopulationHistoryError("서울 생활인구 API 수집에 실패했습니다.") from exc

        if not isinstance(payload, dict) or not isinstance(
            payload.get(SEOUL_POPULATION_SERVICE), dict
        ):
            raise PopulationHistoryError("서울 생활인구 API 응답 형식이 올바르지 않습니다.")
        body = payload[SEOUL_POPULATION_SERVICE]
        try:
            page_total = int(body["list_total_count"])
            page_rows = body["row"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PopulationHistoryError("서울 생활인구 API 페이지 정보가 올바르지 않습니다.") from exc
        if not isinstance(page_rows, list) or page_total < 0:
            raise PopulationHistoryError("서울 생활인구 API row 형식이 올바르지 않습니다.")
        if total is None:
            total = page_total
        elif total != page_total:
            raise PopulationHistoryError("서울 생활인구 API 페이지 수가 일관되지 않습니다.")
        if not page_rows and len(rows) < total:
            raise PopulationHistoryError("서울 생활인구 API pagination이 불완전합니다.")
        rows.extend(page_rows)
        start += POPULATION_PAGE_SIZE

    if len(rows) != total:
        raise PopulationHistoryError("서울 생활인구 API 수집 행 수가 일치하지 않습니다.")
    return normalize_population_rows(rows)


def _read_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_history()
    try:
        frame = pd.read_csv(path, dtype={"행정동코드": "string"})
    except (OSError, ValueError) as exc:
        raise PopulationHistoryError("기존 생활인구 history를 읽을 수 없습니다.") from exc
    if set(frame.columns) != set(REQUIRED_HISTORY_COLUMNS):
        raise PopulationHistoryError("기존 생활인구 history 스키마가 올바르지 않습니다.")
    frame = frame.loc[:, REQUIRED_HISTORY_COLUMNS]
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    frame["행정동코드"] = frame["행정동코드"].astype("string").str.strip()
    frame["생활인구합계"] = pd.to_numeric(frame["생활인구합계"], errors="coerce")
    if frame.isna().any().any() or (frame["행정동코드"] == "").any():
        raise PopulationHistoryError("기존 생활인구 history 값이 올바르지 않습니다.")
    return frame


def get_complete_history_dates(
    *,
    history_path: str | Path = DEFAULT_HISTORY_PATH,
) -> list[date]:
    """Return dates whose stored rows pass the existing full-day validation."""
    frame = _read_history(Path(history_path))
    complete_dates = []
    for stored_day, day_frame in frame.groupby(frame["datetime"].dt.normalize()):
        try:
            validate_daily_population(day_frame, stored_day)
        except PopulationHistoryError:
            continue
        complete_dates.append(stored_day.date())
    return complete_dates


def _atomic_write_history(frame: pd.DataFrame, path: Path) -> None:
    # 임시 파일을 완성한 뒤 교체해 수집·저장 실패가 기존 정상 history를 훼손하지 않게 한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
        ) as temp:
            temp_name = temp.name
        frame.to_csv(temp_name, index=False)
        os.replace(temp_name, path)
    except OSError as exc:
        raise PopulationHistoryError("생활인구 history 저장에 실패했습니다.") from exc
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def update_population_history(
    day: str | date | pd.Timestamp,
    *,
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    api_key: str | None = None,
    http_get=requests.get,
) -> pd.DataFrame:
    """Safely add one validated day; failed collection leaves existing history intact."""
    requested_day = _normalize_day(day)
    path = Path(history_path)
    existing = _read_history(path)
    # 이미 완전한 하루가 있으면 API 재호출 없이 그대로 재사용한다.
    stored_day = existing[existing["datetime"].dt.normalize() == requested_day]
    if not stored_day.empty:
        try:
            validate_daily_population(stored_day, requested_day)
        except PopulationHistoryError:
            pass
        else:
            return existing.reset_index(drop=True)

    new_day = fetch_population_day(requested_day, api_key=api_key, http_get=http_get)
    validate_daily_population(new_day, requested_day)
    # 같은 시각·행정동은 새 수집값으로 덮어쓰고, 보존 기간 밖 데이터만 정리한다.
    combined = pd.concat([existing, new_day], ignore_index=True)
    combined = combined.drop_duplicates(["datetime", "행정동코드"], keep="last")
    latest_day = combined["datetime"].max().normalize()
    cutoff = latest_day - pd.Timedelta(days=HISTORY_RETENTION_DAYS - 1)
    combined = combined[combined["datetime"] >= cutoff].sort_values(
        ["datetime", "행정동코드"]
    )
    _atomic_write_history(combined.loc[:, REQUIRED_HISTORY_COLUMNS], path)
    return combined.reset_index(drop=True)


def load_population_history(
    issue_time: object | None = None,
    *,
    history_path: str | Path = DEFAULT_HISTORY_PATH,
) -> pd.DataFrame:
    """Return provider-compatible history, optionally limited to the three D-4 lags."""
    frame = _read_history(Path(history_path))
    if issue_time is not None:
        try:
            # 생활인구 history는 정시 데이터이므로 분·초가 있는 요청도 해당 시각의 정시로 맞춘다.
            issue = pd.Timestamp(issue_time).floor("h")
        except (TypeError, ValueError) as exc:
            raise PopulationHistoryError("issue_time 형식이 올바르지 않습니다.") from exc
        required_times = [
            issue - pd.Timedelta(hours=96),
            issue - pd.Timedelta(hours=168),
            issue - pd.Timedelta(hours=336),
        ]
        frame = frame[frame["datetime"].isin(required_times)]
    return frame.loc[:, REQUIRED_HISTORY_COLUMNS].sort_values(
        ["datetime", "행정동코드"]
    ).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="서울 생활인구 하루 history 수집")
    parser.add_argument("day", help="수집 날짜 (YYYY-MM-DD)")
    parser.add_argument("--history-path", default=str(DEFAULT_HISTORY_PATH))
    args = parser.parse_args()
    history = update_population_history(args.day, history_path=args.history_path)
    print(f"생활인구 history 갱신 완료: {len(history)} rows")


if __name__ == "__main__":
    main()
