"""Run with Python 3.10+: python download_popup_json.py"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from popup_service import normalize_popup_place

API_URL = "https://152-69-195-242.sslip.io/api/export/json"
KST = timezone(timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent / "popup_data"
POPUP_DATA_PATH = OUTPUT_DIR / "popup_places.json"
POPUP_BACKUP_PATH = OUTPUT_DIR / "popup_places_backup.json"


def _validate_content(content):
    records = json.loads(content)

    if not isinstance(records, list) or not records:
        raise ValueError("응답이 비어 있지 않은 팝업 목록이어야 합니다.")

    if not any(normalize_popup_place(record) is not None for record in records):
        raise ValueError("정상화 가능한 팝업 데이터가 없습니다.")

    return records


def _is_valid_popup_file(path):
    try:
        _validate_content(path.read_bytes())
    except (OSError, ValueError, json.JSONDecodeError):
        return False

    return True


def download_today(token):
    date = datetime.now(KST).strftime("%Y%m%d")
    request = Request(
        f"{API_URL}?date={date}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=120) as response:
        content = response.read()
    records = _validate_content(content)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temporary = None
    backup_temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=OUTPUT_DIR, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)

        if POPUP_DATA_PATH.exists() and _is_valid_popup_file(POPUP_DATA_PATH):
            with tempfile.NamedTemporaryFile(
                dir=OUTPUT_DIR,
                suffix=".backup.tmp",
                delete=False,
            ) as file:
                backup_temporary = Path(file.name)
            shutil.copy2(POPUP_DATA_PATH, backup_temporary)
            backup_temporary.replace(POPUP_BACKUP_PATH)
            backup_temporary = None

        temporary.replace(POPUP_DATA_PATH)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if backup_temporary is not None:
            backup_temporary.unlink(missing_ok=True)

    return POPUP_DATA_PATH, len(records)


def main():
    load_dotenv()
    token = os.environ.get("CRAWLER_API_TOKEN", "").strip()
    if not token:
        print("실패: .env에 CRAWLER_API_TOKEN을 설정해 주세요.", file=sys.stderr)
        return 1

    try:
        target, count = download_today(token)
    except HTTPError as error:
        messages = {
            401: "토큰 인증에 실패했습니다. 기존 크롤러 API 토큰을 확인해 주세요.",
            403: "다운로드 권한이 없습니다.",
            404: "오늘 날짜의 JSON 파일이 없습니다. 크롤링 완료 후 다시 실행해 주세요.",
        }
        print("실패: " + messages.get(error.code, f"서버 응답 오류 (HTTP {error.code})"), file=sys.stderr)
        return 1
    except (URLError, TimeoutError):
        print("실패: 서버 연결 또는 응답 시간에 문제가 있습니다. 잠시 후 다시 실행해 주세요.", file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f"실패: JSON 확인 또는 파일 저장 오류: {error}", file=sys.stderr)
        return 1

    print(f"다운로드 완료: {count}건")
    print(f"저장 위치: {target}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n다운로드를 취소했습니다.", file=sys.stderr)
        sys.exit(1)
