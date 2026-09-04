from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from crawlers.popga import crawl_popga, save_jsonl
from crawlers.popga_detail import fetch_details, save_jsonl as save_detail_jsonl
from crawlers.popga_detail_probe import probe_popga_details


SEOUL_TZ = ZoneInfo("Asia/Seoul")
SOURCE_STATUS_MAP = {
    "운영중": "ACTIVE",
    "오픈 예정": "UPCOMING",
    "종료": "ENDED",
}



def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def previous_run_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir() and (p / "normalized_list_preview.jsonl").exists()]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def unchanged_active_ids(current: list[dict], previous: list[dict]) -> set[str]:
    previous_by_id = {str(row.get("source_id")): row for row in previous}
    keys = ("name_raw", "start_date", "end_date", "detail_url")
    result: set[str] = set()
    for row in current:
        if row.get("status") != "ACTIVE":
            continue
        prior = previous_by_id.get(str(row.get("source_id")))
        if prior and all(row.get(key) == prior.get(key) for key in keys):
            result.add(str(row.get("source_id")))
    return result

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Popga 서울 목록 수집 및 상세 DOM 소수 검증"
    )
    parser.add_argument(
        "--detail-probe",
        type=int,
        default=0,
        metavar="N",
        help="목록 수집 후 공개 상세페이지 N건의 HTML/본문을 검증 저장",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="목록의 공개 상세페이지를 저빈도로 수집하고 구조화 데이터 파싱",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=None,
        metavar="N",
        help="--details 실행 대상을 앞 N건으로 제한(검증용)",
    )
    parser.add_argument(
        "--detail-cache-hours",
        type=float,
        default=float(os.getenv("POPGA_DETAIL_CACHE_HOURS", "54")),
        help="변경 없는 ACTIVE 상세의 이전 HTML 재사용 TTL(시간), 기본 54",
    )
    parser.add_argument(
        "--no-detail-cache",
        action="store_true",
        help="이전 실행 상세 캐시를 재사용하지 않고 전부 live fetch",
    )
    return parser.parse_args()


def derive_status(start_date: str, end_date: str | None) -> str:
    today = datetime.now(SEOUL_TZ).date()
    start = date.fromisoformat(start_date)

    if today < start:
        return "UPCOMING"
    if end_date is None:
        return "ACTIVE"
    end = date.fromisoformat(end_date)
    if today > end:
        return "ENDED"
    return "ACTIVE"


def enrich_with_details(list_rows: list[dict], details: list[dict]) -> list[dict]:
    detail_by_id = {str(x["source_id"]): x for x in details if x.get("fetch_ok")}
    enriched: list[dict] = []

    for row in list_rows:
        detail = detail_by_id.get(str(row["source_id"]))
        out = dict(row)
        if not detail:
            out["detail_fetch_ok"] = False
            enriched.append(out)
            continue

        category_names = [
            str(x.get("name"))
            for x in detail.get("categories_raw") or []
            if x.get("name")
        ]
        invalid_detail_range = "invalid_date_range" in (
            detail.get("parse_warnings") or []
        )
        if invalid_detail_range:
            # 상세 파싱값과 원천 payload는 details.jsonl에 그대로 보존하고,
            # normalized 값만 검증된 목록 날짜로 안전하게 되돌린다.
            start_date = row["start_date"]
            end_date = row.get("end_date")
        else:
            start_date = detail.get("start_date_detail") or row["start_date"]
            # embedded payload가 있으면 null도 원천의 '종료일 미정' 값으로 존중한다.
            end_date = (
                detail.get("end_date_detail")
                if detail.get("parse_source") == "nextjs_embedded_data"
                else row.get("end_date")
            )

        out.update({
            "detail_fetch_ok": True,
            "detail_parse_source": detail.get("parse_source"),
            "event_type_raw": detail.get("event_type_raw"),
            "name": detail.get("title_detail") or row.get("name"),
            "address_raw": detail.get("address_raw"),
            "address": detail.get("road_address"),
            "address_base": detail.get("road_address"),
            "address_detail_raw": detail.get("address_detail_raw"),
            "venue_name": detail.get("venue_name"),
            "district": detail.get("district"),
            "start_date": start_date,
            "end_date": end_date,
            "status": derive_status(start_date, end_date),
            "category": category_names[0] if category_names else row.get("category"),
            "categories": category_names,
            "tags": detail.get("tags_raw") or [],
            "description": detail.get("description_raw"),
            "ai_summary_source_raw": detail.get("ai_summary_raw"),
            "operation_hours": detail.get("operation_hours_raw") or [],
            "latitude": detail.get("latitude"),
            "longitude": detail.get("longitude"),
            "benefits": detail.get("benefits_nonempty") or [],
            "website_links": detail.get("website_raw") or {},
            "reservation_info_present": detail.get("reservation_info_present"),
            "reservation_required": detail.get("reservation_required"),
            "reservation_open_at": detail.get("reservation_open_at"),
            "reservation_close_at": detail.get("reservation_close_at"),
            "reservation_url": detail.get("reservation_url"),
            "detail_parse_warnings": detail.get("parse_warnings") or [],
        })
        enriched.append(out)

    return enriched


def main() -> None:
    args = parse_args()
    timestamp = datetime.now(SEOUL_TZ).strftime("%Y%m%d_%H%M%S")
    runs_base = Path("data/popga/runs")
    previous_dir = previous_run_dir(runs_base)
    run_dir = runs_base / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] Popga 공개 목록 렌더링/스크롤")
    items, html_path, crawl_diagnostics = crawl_popga(run_dir)
    print(f"      렌더링 HTML: {html_path}")

    print("[2/5] 서울 후보 카드 파싱")
    raw_path = run_dir / "raw_seoul_candidates.jsonl"
    save_jsonl(items, raw_path)
    print(f"      서울 후보: {len(items)}건")

    normalized = []
    for item in items:
        row = item.__dict__.copy()
        row.update({
            "name": item.name_raw,
            "area": item.area_raw,
            "category": item.category_raw,
            "status": derive_status(
                item.start_date,
                item.end_date,
            ),
        })
        normalized.append(row)

    normalized_path = run_dir / "normalized_list_preview.jsonl"
    with normalized_path.open("w", encoding="utf-8") as f:
        for row in normalized:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("[3/5] 날짜 기준 상태 계산")
    counts = Counter(x["status"] for x in normalized)
    status_mismatches = [
        x for x in normalized
        if SOURCE_STATUS_MAP.get(x["source_status"]) != x["status"]
    ]

    detail_probe_report = None
    if args.detail_probe > 0:
        print(f"      Popga 공개 상세페이지 {args.detail_probe}건 probe")
        detail_probe_report = probe_popga_details(
            normalized,
            run_dir / "detail_probe",
            count=args.detail_probe,
        )

    detail_report = None
    details: list[dict] = []
    if args.details:
        detail_items = normalized
        if args.detail_limit is not None:
            detail_items = detail_items[:max(0, args.detail_limit)]
        print(f"[4/5] Popga 공개 상세페이지 수집/파싱: {len(detail_items)}건")
        cache_ids: set[str] = set()
        previous_html_dir = None
        if previous_dir and not args.no_detail_cache:
            previous_rows = load_jsonl(previous_dir / "normalized_list_preview.jsonl")
            cache_ids = unchanged_active_ids(detail_items, previous_rows)
            previous_html_dir = previous_dir / "detail_html"
        print(
            f"      상세 캐시 후보: {len(cache_ids)}건 / live 우선: "
            f"{len(detail_items) - len(cache_ids)}건"
        )
        details = fetch_details(
            detail_items,
            run_dir / "detail_html",
            cache_dir=previous_html_dir,
            cache_ids=cache_ids,
            cache_max_age_hours=max(0.0, args.detail_cache_hours),
        )
        save_detail_jsonl(details, run_dir / "details.jsonl")
        enriched = enrich_with_details(normalized, details)
        save_detail_jsonl(enriched, run_dir / "normalized_with_details.jsonl")
        list_by_id = {str(x["source_id"]): x for x in detail_items}

        detail_report = {
            "requested_count": len(detail_items),
            "success_count": sum(bool(x.get("fetch_ok")) for x in details),
            "failed_count": sum(not bool(x.get("fetch_ok")) for x in details),
            "cache_hit_count": sum(bool(x.get("fetched_from_cache")) for x in details),
            "live_fetch_count": sum(not bool(x.get("fetched_from_cache")) for x in details),
            "embedded_data_count": sum(
                x.get("parse_source") == "nextjs_embedded_data" for x in details
            ),
            "dom_fallback_count": sum(
                x.get("parse_source") == "dom_fallback" for x in details
            ),
            "road_address_missing_count": sum(
                not x.get("road_address") for x in details if x.get("fetch_ok")
            ),
            "description_missing_count": sum(
                not x.get("description_raw") for x in details if x.get("fetch_ok")
            ),
            "end_date_missing_count": sum(
                not x.get("end_date_detail") for x in details if x.get("fetch_ok")
            ),
            "reservation_info_count": sum(
                bool(x.get("reservation_info_present")) for x in details
            ),
            "event_type_counts": dict(Counter(
                x.get("event_type_raw") or "UNKNOWN"
                for x in details if x.get("fetch_ok")
            )),
            "name_mismatch_count": sum(
                bool(x.get("fetch_ok"))
                and x.get("title_detail")
                != list_by_id.get(str(x["source_id"]), {}).get("name_raw")
                for x in details
            ),
            "start_date_mismatch_count": sum(
                bool(x.get("fetch_ok"))
                and x.get("start_date_detail")
                != list_by_id.get(str(x["source_id"]), {}).get("start_date")
                for x in details
            ),
            "end_date_mismatch_count": sum(
                bool(x.get("fetch_ok"))
                and x.get("end_date_detail")
                != list_by_id.get(str(x["source_id"]), {}).get("end_date")
                for x in details
            ),
        }
    else:
        print("[4/5] 상세 전체 수집 건너뜀 (--details 미지정)")

    report = {
        "version": "1.0.0",
        "source": "popga",
        "run_timestamp": timestamp,
        "candidate_count": len(normalized),
        "missing_end_date_count": sum(
            x["end_date"] is None for x in normalized
        ),
        "status_counts": dict(counts),
        "source_status_mismatch_count": len(status_mismatches),
        "source_status_counts": dict(
            Counter(x.source_status for x in items)
        ),
        "area_counts": dict(
            Counter(x.area_raw for x in items).most_common()
        ),
        "crawl_diagnostics": crawl_diagnostics,
        "detail_probe": detail_probe_report,
        "detail_fetch": detail_report,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[5/5] 결과 저장 완료")
    print()
    print("=== Popga v1.0.0 상세 타입/주소 보정 결과 ===")
    print(f"서울 후보: {len(normalized)}건")
    print(f"오늘 운영중: {counts.get('ACTIVE', 0)}건")
    print(f"오픈예정: {counts.get('UPCOMING', 0)}건")
    print(f"종료로 계산됨: {counts.get('ENDED', 0)}건")
    print(f"상세 URL 누락: {crawl_diagnostics['missing_detail_url_count']}건")
    print(f"fallback source_id: {crawl_diagnostics['fallback_id_count']}건")
    print(f"종료일 추후 공지: {crawl_diagnostics['missing_end_date_count']}건")
    print(f"source/날짜 상태 불일치: {len(status_mismatches)}건")
    print(f"파서 모드: {crawl_diagnostics['parser_mode']}")
    if detail_report:
        print(f"상세 조회 성공/실패: {detail_report['success_count']} / {detail_report['failed_count']}")
        print(f"상세 캐시/live: {detail_report['cache_hit_count']} / {detail_report['live_fetch_count']}")
        print(f"내장 구조화 데이터 파싱: {detail_report['embedded_data_count']}건")
        print(f"DOM fallback: {detail_report['dom_fallback_count']}건")
        print(f"상세 주소 누락: {detail_report['road_address_missing_count']}건")
        print(f"상세 설명 누락: {detail_report['description_missing_count']}건")
        print(f"상세 원천 타입: {detail_report['event_type_counts']}")
        print(f"목록/상세 이름 불일치: {detail_report['name_mismatch_count']}건")
        print(f"목록/상세 시작일 불일치: {detail_report['start_date_mismatch_count']}건")
        print(f"목록/상세 종료일 불일치: {detail_report['end_date_mismatch_count']}건")
    print(f"실행 결과 폴더: {run_dir}")
    print()
    print("※ 이 단계는 Popga 목록/상세 구조 검증용입니다.")
    print("※ 아직 DayForYou와 중복제거/병합하지 않습니다.")


if __name__ == "__main__":
    main()
