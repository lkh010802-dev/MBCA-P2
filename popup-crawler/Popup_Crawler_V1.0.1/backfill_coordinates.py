from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path

from integration.geocode import DEFAULT_CACHE_PATH, enrich_missing_coordinates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="기존 backend popup CSV의 누락 latitude/longitude만 안전하게 보완"
    )
    parser.add_argument("input_csv", type=Path, help="예: output/20260902_popup.csv")
    parser.add_argument("--output", type=Path, help="출력 CSV. 생략 시 *_geocoded.csv")
    parser.add_argument("--in-place", action="store_true", help="원본 CSV를 원자적으로 교체")
    parser.add_argument("--no-api", action="store_true", help="Kakao API 호출 없이 캐시/동일주소 재사용만 수행")
    parser.add_argument(
        "--geocode-cache", type=Path, default=DEFAULT_CACHE_PATH,
        help="Kakao 지오코딩 캐시 JSON 경로",
    )
    return parser.parse_args()


def _write_csv(rows: list[dict], fieldnames: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    if args.in_place and args.output:
        raise SystemExit("--in-place와 --output은 동시에 사용할 수 없습니다.")
    if not args.input_csv.exists():
        raise FileNotFoundError(args.input_csv)

    with args.input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for required in ("latitude", "longitude"):
        if required not in fieldnames:
            raise ValueError(f"CSV에 {required} 컬럼이 없습니다.")

    output = (
        args.input_csv
        if args.in_place
        else args.output or args.input_csv.with_name(f"{args.input_csv.stem}_geocoded.csv")
    )

    enriched, report, unresolved = enrich_missing_coordinates(
        rows,
        cache_path=args.geocode_cache,
        use_api=not args.no_api,
    )
    _write_csv(enriched, fieldnames, output)

    report_path = output.with_suffix(".geocode_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    unresolved_path = output.with_suffix(".geocode_unresolved.csv")
    unresolved_fields = [
        *fieldnames,
        "geocode_address_query",
        "geocode_keyword_queries",
        "geocode_unresolved_reason",
    ]
    _write_csv(unresolved, unresolved_fields, unresolved_path)

    print(f"입력: {args.input_csv} ({len(rows)}건)")
    print(f"출력: {output}")
    print(
        f"좌표 누락: {report['missing_before']} → {report['missing_after']} / "
        f"보완 {report['filled_total']}건"
    )
    print(
        f"캐시 {report['cache_hits']} / 동일주소 {report['same_address_reused']} / "
        f"Kakao주소 {report['kakao_address_filled']} / Kakao키워드 {report['kakao_keyword_filled']} / "
        f"API 호출 {report['api_calls']}"
    )
    if not report.get("api_enabled", True):
        print("--no-api: Kakao API 단계는 건너뛰었습니다.")
    elif not report["api_key_present"] and report["enabled"]:
        print("KAKAO_REST_API_KEY가 없어 API 단계는 건너뛰었습니다.")
    print(f"보고서: {report_path}")
    print(f"미해결: {unresolved_path} ({len(unresolved)}건)")


if __name__ == "__main__":
    main()
