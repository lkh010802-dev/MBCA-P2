from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend_adapter.popup_backend_adapter import export_backend_json, find_latest_popup_csv


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert the crawler's daily popup CSV into backend common place JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Daily popup CSV. If omitted, the newest output/*_popup.csv is used.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Backend JSON output path. Default: backend_output/YYYYMMDD_popup_places.json",
    )
    parser.add_argument(
        "--no-latest-copy",
        action="store_true",
        help="Do not refresh backend_output/latest_popup_places.json",
    )
    return parser.parse_args()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main() -> None:
    args = parse_args()
    csv_path = _resolve(args.input) if args.input else find_latest_popup_csv(ROOT / "output")
    if not csv_path.exists():
        raise SystemExit(f"input CSV not found: {csv_path}")

    date_prefix = csv_path.name.split("_popup.csv", 1)[0]
    output_path = (
        _resolve(args.output)
        if args.output
        else ROOT / "backend_output" / f"{date_prefix}_popup_places.json"
    )
    latest_path = None if args.no_latest_copy else ROOT / "backend_output" / "latest_popup_places.json"
    report = export_backend_json(csv_path, output_path, latest_path=latest_path)
    report_path = ROOT / "backend_output" / "latest_export_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Popup Backend Export ===")
    print(f"input_csv={csv_path}")
    print(f"output_json={output_path}")
    print(f"count={report['count']}")
    print(
        f"today_hours={report['today_hours_count']}/{report['count']} "
        f"missing={report['today_hours_missing_count']}"
    )


if __name__ == "__main__":
    main()
