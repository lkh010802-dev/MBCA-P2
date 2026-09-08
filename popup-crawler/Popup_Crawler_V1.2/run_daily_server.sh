#!/usr/bin/env bash

set -u

PROJECT_DIR="/home/ubuntu/popup-crawler"
STATE_DIR="/home/ubuntu/Popup_Crawler_STATE"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
REPORT="$PROJECT_DIR/data/daily/latest_report.json"

cd "$PROJECT_DIR" || exit 2

if [ ! -x "$PYTHON" ]; then
    echo "[ERROR] Python venv not found: $PYTHON"
    exit 2
fi

mkdir -p "$STATE_DIR"
mkdir -p "$STATE_DIR/dayforyou_detail_html"

export POPUP_STATE_DIR="$STATE_DIR"
export POPUP_MASTER_PATH="$STATE_DIR/canonical_master.jsonl"
export POPUP_PRODUCTION="1"
export POPGA_SCROLL_PAUSE="2.0"
export POPGA_MAX_SCROLLS="60"
export DAYFORYOU_DETAIL_CACHE_DIR="$STATE_DIR/dayforyou_detail_html"
export DAYFORYOU_DETAIL_CACHE_HOURS="54"

echo "[STATE] POPUP_STATE_DIR=$POPUP_STATE_DIR"
echo "[STATE] POPUP_MASTER_PATH=$POPUP_MASTER_PATH"
echo "[STATE] DAYFORYOU_DETAIL_CACHE_DIR=$DAYFORYOU_DETAIL_CACHE_DIR"
echo "[STATE] DAYFORYOU_DETAIL_CACHE_HOURS=$DAYFORYOU_DETAIL_CACHE_HOURS"

if [ ! -f "$POPUP_MASTER_PATH" ]; then
    echo "[ERROR] Production master not found:"
    echo "$POPUP_MASTER_PATH"
    exit 3
fi

MARKER="$(mktemp /tmp/popup_crawler_XXXXXX)"
touch "$MARKER"

"$PYTHON" -u run_daily.py --sequential-sources
CRAWLER_EXIT=$?

if [ ! -f "$REPORT" ]; then
    echo "[ERROR] Daily report was not created."
    rm -f "$MARKER"
    exit "$CRAWLER_EXIT"
fi

if [ ! "$REPORT" -nt "$MARKER" ]; then
    echo "[ERROR] Daily report exists but was not updated by this run."
    rm -f "$MARKER"
    exit "$CRAWLER_EXIT"
fi

rm -f "$MARKER"

echo
echo "[RESULT]"
echo "crawler_exit_code=$CRAWLER_EXIT"

"$PYTHON" - <<'PY'
import json
from pathlib import Path

report_path = Path("data/daily/latest_report.json")

try:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    print("status=" + str(data.get("status")))
    print("report=data/daily/latest_report.json")
except Exception as e:
    print(f"report_parse_error={e}")
PY

exit "$CRAWLER_EXIT"
