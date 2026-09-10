"""Download today's popup JSON with Python 3.10 or newer."""

import getpass
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# 로컬에서 직접 넣을 수도 있지만, 환경변수 사용을 권장합니다. Bearer는 붙이지 않습니다.
CRAWLER_API_TOKEN = ""
API_URL = os.environ.get(
    "CRAWLER_API_URL",
    "https://crawler.example.com/api/export/json",
).strip()
KST = timezone(timedelta(hours=9))
OUTPUT_DIR = Path(__file__).resolve().parent / "popup_data"


def download_today(token):
    date = datetime.now(KST).strftime("%Y%m%d")
    request = Request(
        f"{API_URL}?date={date}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=120) as response:
        content = response.read()
    records = json.loads(content)
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("응답이 팝업 목록 형식이 아닙니다.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{date}_popup_places.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=OUTPUT_DIR, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target, len(records)


def main():
    token = CRAWLER_API_TOKEN.strip() or os.environ.get("CRAWLER_API_TOKEN", "").strip()
    if not token:
        if not sys.stdin.isatty():
            print("실패: CRAWLER_API_TOKEN 환경변수를 설정해 주세요.", file=sys.stderr)
            return 1
        token = getpass.getpass("크롤러 API 토큰 입력 (화면에 표시되지 않음): ").strip()
    if not token:
        print("실패: 토큰이 비어 있습니다.", file=sys.stderr)
        return 1

    try:
        target, count = download_today(token)
    except HTTPError as error:
        messages = {
            401: "토큰 인증에 실패했습니다. 크롤러 API 토큰을 확인해 주세요.",
            403: "다운로드 권한이 없습니다.",
            404: "오늘 날짜의 JSON 파일이 없습니다. 크롤링 완료 후 다시 실행해 주세요.",
        }
        print("실패: " + messages.get(error.code, f"서버 응답 오류 (HTTP {error.code})"), file=sys.stderr)
        return 1
    except (URLError, TimeoutError):
        print("실패: 서버 연결 또는 응답 시간에 문제가 있습니다.", file=sys.stderr)
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
