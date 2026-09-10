"""Remove crawler run directories older than the retention period.

Dry run is the default. Pass --apply to actually remove directories.
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_DIR = Path("/home/ubuntu/popup-crawler")
STATUS_FILE = Path("/home/ubuntu/Popup_Crawler_STATE/api_crawler_status.json")
RUN_ROOTS = (
    PROJECT_DIR / "data/runs",
    PROJECT_DIR / "data/popga/runs",
    PROJECT_DIR / "data/popply/runs",
    PROJECT_DIR / "data/integration/runs",
    PROJECT_DIR / "data/daily/runs",
)
RUN_NAME = re.compile(r"^\d{8}_\d{6}$")
SEOUL = ZoneInfo("Asia/Seoul")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def crawler_is_running():
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        status = {}
    if status.get("status") == "running":
        return True

    process_names = {
        "run_daily.py",
        "run.py",
        "run_popga.py",
        "run_popply.py",
        "run_integrate.py",
    }
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            parts = (entry / "cmdline").read_bytes().split(b"\0")
            args = [part.decode("utf-8", "ignore") for part in parts if part]
        except (OSError, PermissionError):
            continue
        if any(Path(arg).name in process_names for arg in args):
            return True
    return False


def directory_size(path):
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def human_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024


def candidates(root, cutoff):
    if not root.is_dir():
        return [], None
    valid = []
    for path in root.iterdir():
        if not path.is_dir() or path.is_symlink() or not RUN_NAME.fullmatch(path.name):
            continue
        try:
            stamp = datetime.strptime(path.name, "%Y%m%d_%H%M%S").replace(tzinfo=SEOUL)
        except ValueError:
            continue
        valid.append((path, stamp))
    newest = max(valid, key=lambda item: item[1], default=(None, None))[0]
    old = [path for path, stamp in valid if stamp < cutoff and path != newest]
    return sorted(old), newest


def main():
    args = parse_args()
    if args.days < 1:
        raise SystemExit("--days must be at least 1")
    if crawler_is_running():
        raise SystemExit("크롤러가 실행 중이어서 정리를 중단했습니다.")

    cutoff = datetime.now(SEOUL) - timedelta(days=args.days)
    targets = []
    print("기준:", cutoff.strftime("%Y-%m-%d %H:%M:%S KST"))
    for root in RUN_ROOTS:
        old, newest = candidates(root, cutoff)
        print(f"\n{root}")
        print("  최신 보존:", newest.name if newest else "없음")
        for path in old:
            size = directory_size(path)
            targets.append((root.resolve(), path, size))
            print(f"  대상: {path.name} ({human_size(size)})")

    print(f"\n대상: {len(targets)}개, 예상 확보: {human_size(sum(x[2] for x in targets))}")
    if not args.apply:
        print("미리보기만 완료했습니다. 실제 삭제는 하지 않았습니다.")
        return

    for root, path, _ in targets:
        resolved = path.resolve()
        if resolved.parent != root or not RUN_NAME.fullmatch(resolved.name):
            raise RuntimeError(f"안전 확인 실패: {path}")
        shutil.rmtree(resolved)
        print("삭제:", resolved)
    print("정리 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"정리 실패: {error}", file=sys.stderr)
        raise SystemExit(1)
