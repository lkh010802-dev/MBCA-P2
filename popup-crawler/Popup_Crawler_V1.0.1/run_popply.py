from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from crawlers.popply import crawl_popply_lists, save_jsonl
from crawlers.popply_detail import fetch_details


SEOUL_TZ = ZoneInfo("Asia/Seoul")
SOURCE_STATUS_MAP = {"진행 중": "ACTIVE", "오픈 예정": "UPCOMING", "종료": "ENDED"}


def derive_status(start_date: str, end_date: str | None, *, today: date) -> str:
    start = date.fromisoformat(start_date)
    if today < start:
        return "UPCOMING"
    if end_date is None or today <= date.fromisoformat(end_date):
        return "ACTIVE"
    return "ENDED"


def enrich_with_details(list_rows: list[dict], details: list[dict], *, today: date) -> list[dict]:
    detail_by_id = {str(x["source_id"]): x for x in details if x.get("fetch_ok")}
    result: list[dict] = []
    for row in list_rows:
        out = dict(row)
        detail = detail_by_id.get(str(row["source_id"]))
        if not detail:
            out["detail_fetch_ok"] = False
            result.append(out)
            continue
        invalid = "invalid_date_range" in (detail.get("parse_warnings") or [])
        start = (
            row["start_date"] if invalid
            else detail.get("physical_start_date")
            or detail.get("start_date_detail")
            or row["start_date"]
        )
        end = (
            row.get("end_date") if invalid
            else detail.get("physical_end_date")
            or detail.get("end_date_detail")
            or row.get("end_date")
        )
        out.update({
            "detail_fetch_ok": True,
            "detail_parse_source": detail.get("parse_source"),
            "source_header_start_date": detail.get("start_date_detail"),
            "source_header_end_date": detail.get("end_date_detail"),
            "physical_period_source": detail.get("physical_period_source"),
            "name": detail.get("title_detail") or row.get("name"),
            "category": detail.get("category_detail") or row.get("category"),
            "categories": [detail.get("category_detail")] if detail.get("category_detail") else [],
            "event_type_raw": detail.get("category_detail"),
            "start_date": start,
            "end_date": end,
            "status": derive_status(start, end, today=today),
            "address": detail.get("address"),
            "address_base": detail.get("address_base"),
            "venue_name": detail.get("venue_name"),
            "district": detail.get("district"),
            "description": detail.get("description_raw"),
            "notice": detail.get("notice_raw"),
            "operation_hours": detail.get("operation_hours_raw") or [],
            "tags": detail.get("tags_raw") or [],
            "website_links": detail.get("website_raw") or {},
            "reservation_info_present": detail.get("reservation_info_present"),
            "reservation_required": detail.get("reservation_required"),
            "reservation_url": detail.get("reservation_url"),
            "amenities": detail.get("amenities_raw") or [],
            "image_url": detail.get("main_image_url") or row.get("image_url"),
            "detail_parse_warnings": detail.get("parse_warnings") or [],
        })
        result.append(out)
    return result



def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def previous_run_dirs(base: Path, *, limit: int = 6) -> list[Path]:
    if not base.exists():
        return []
    candidates = [
        p for p in base.iterdir()
        if p.is_dir() and (p / "normalized_list_preview.jsonl").exists()
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:max(1, limit)]


def previous_run_dir(base: Path) -> Path | None:
    candidates = previous_run_dirs(base, limit=1)
    return candidates[0] if candidates else None


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
    parser = argparse.ArgumentParser(description="Popply 공개 목록/상세 저빈도 수집")
    parser.add_argument("--details", action="store_true", help="서울 후보의 공개 상세 DOM도 수집")
    parser.add_argument("--detail-limit", type=int, default=None, metavar="N", help="상세 수집을 앞 N건으로 제한")
    parser.add_argument("--detail-delay-ms", type=int, default=int(os.getenv("POPPLY_DETAIL_DELAY_MS", "700")), help="상세 요청 사이 대기(ms), 기본 700")
    parser.add_argument("--detail-settle-ms", type=int, default=int(os.getenv("POPPLY_DETAIL_SETTLE_MS", "250")), help="상세 DOM 확인 후 추가 안정화 대기(ms), 기본 250")
    parser.add_argument("--detail-cache-hours", type=float, default=float(os.getenv("POPPLY_DETAIL_CACHE_HOURS", "54")), help="변경 없는 ACTIVE 상세 캐시 TTL(시간), 기본 54")
    parser.add_argument("--no-detail-cache", action="store_true", help="이전 상세 캐시를 사용하지 않고 전부 live fetch")
    parser.add_argument("--headed", action="store_true", help="Playwright 브라우저 창 표시")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = datetime.now(SEOUL_TZ)
    today = now.date()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    runs_base = Path("data/popply/runs")
    previous_dirs = previous_run_dirs(runs_base, limit=6)
    previous_dir = previous_dirs[0] if previous_dirs else None
    run_dir = runs_base / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] Popply 공개 목록 ACTIVE/UPCOMING 렌더링")
    items, diagnostics = crawl_popply_lists(run_dir, headless=not args.headed)
    save_jsonl(items, run_dir / "raw_seoul_candidates.jsonl")
    print(f"      서울 카드: {len(items)}건")

    print("[2/5] 목록 공통 필드 정규화")
    normalized = []
    for item in items:
        row = item.__dict__.copy()
        row.update({
            "name": item.name_raw,
            "area": item.area_raw,
            "category": item.category_raw,
            "categories": [item.category_raw] if item.category_raw else [],
            "status": derive_status(item.start_date, item.end_date, today=today),
            "address": None,
            "address_base": None,
            "venue_name": None,
            "district": item.area_raw.split()[-1] if item.area_raw else None,
            "description": None,
            "tags": [],
            "operation_hours": [],
            "website_links": {},
            "reservation_required": None,
            "reservation_url": None,
            "detail_parse_warnings": [],
        })
        normalized.append(row)
    save_jsonl(normalized, run_dir / "normalized_list_preview.jsonl")

    details: list[dict] = []
    enriched = normalized
    detail_is_partial = False
    if args.details:
        targets = normalized[:max(0, args.detail_limit)] if args.detail_limit is not None else normalized
        detail_is_partial = len(targets) < len(normalized)
        print(f"[3/5] 공개 상세 DOM 수집/파싱: {len(targets)}건")
        cache_ids: set[str] = set()
        cache_dirs: list[Path] = []
        if previous_dir and not args.no_detail_cache:
            previous_rows = load_jsonl(previous_dir / "normalized_list_preview.jsonl")
            cache_ids = unchanged_active_ids(targets, previous_rows)
            cache_dirs = [
                prior / "detail_html"
                for prior in previous_dirs
                if (prior / "detail_html").exists()
            ]
        print(
            f"      상세 캐시 후보: {len(cache_ids)}건 / live 우선: "
            f"{len(targets) - len(cache_ids)}건"
        )
        details = fetch_details(
            targets,
            run_dir / "detail_html",
            delay_ms=max(0, args.detail_delay_ms),
            settle_ms=max(0, args.detail_settle_ms),
            headless=not args.headed,
            cache_dirs=cache_dirs,
            cache_ids=cache_ids,
            cache_max_age_hours=max(0.0, args.detail_cache_hours),
        )
        save_jsonl(details, run_dir / "details.jsonl")
        enriched = enrich_with_details(normalized, details, today=today)
        normalized_detail_name = (
            "normalized_with_details_probe.jsonl"
            if detail_is_partial else "normalized_with_details.jsonl"
        )
        save_jsonl(enriched, run_dir / normalized_detail_name)

        # Daily integration은 상세 핵심필드가 정상적으로 확보된 레코드만 사용한다.
        # 실패/미완성 레코드는 raw 결과에는 그대로 보존하고 quarantine으로 별도 저장한다.
        if not detail_is_partial:
            detail_by_id_all = {str(x.get("source_id")): x for x in details}
            integration_rows = [row for row in enriched if bool(row.get("detail_fetch_ok"))]
            quarantine_rows = []
            for row in enriched:
                if bool(row.get("detail_fetch_ok")):
                    continue
                detail = detail_by_id_all.get(str(row.get("source_id"))) or {}
                q = dict(row)
                q["quarantine_reason"] = (
                    "core_detail_incomplete"
                    if not bool(detail.get("core_detail_complete"))
                    else "detail_fetch_failed"
                )
                q["detail_parse_warnings"] = detail.get("parse_warnings") or q.get("detail_parse_warnings") or []
                q["live_attempt_count"] = detail.get("live_attempt_count")
                quarantine_rows.append(q)
            save_jsonl(integration_rows, run_dir / "normalized_for_integration.jsonl")
            save_jsonl(quarantine_rows, run_dir / "detail_quarantine.jsonl")
    else:
        print("[3/5] 상세 수집 건너뜀 (--details 미지정)")

    print("[4/5] 품질 지표 계산")
    status_counts = dict(Counter(row["status"] for row in enriched))
    source_status_mismatches = [
        row for row in enriched
        if SOURCE_STATUS_MAP.get(row.get("source_status")) != row.get("status")
    ]
    detail_report = None
    if args.details:
        list_by_id = {str(row["source_id"]): row for row in normalized}
        detail_report = {
            "requested_count": len(details),
            "candidate_count": len(normalized),
            "is_partial": detail_is_partial,
            "success_count": sum(bool(x.get("fetch_ok")) for x in details),
            "failed_count": sum(not bool(x.get("fetch_ok")) for x in details),
            "cache_hit_count": sum(bool(x.get("fetched_from_cache")) for x in details),
            "live_fetch_count": sum(not bool(x.get("fetched_from_cache")) for x in details),
            "cache_recovery_count": sum(bool(x.get("cache_recovered_after_live_failure")) for x in details),
            "core_detail_incomplete_count": sum(not bool(x.get("core_detail_complete")) for x in details),
            "retried_live_count": sum(int(x.get("live_attempt_count") or 0) >= 2 for x in details),
            "integration_usable_count": sum(bool(row.get("detail_fetch_ok")) for row in enriched),
            "quarantine_count": sum(not bool(row.get("detail_fetch_ok")) for row in enriched),
            "quarantine_source_ids": [
                str(row.get("source_id")) for row in enriched if not bool(row.get("detail_fetch_ok"))
            ],
            "quarantine_names": [
                str(row.get("name") or row.get("name_raw") or row.get("source_id"))
                for row in enriched if not bool(row.get("detail_fetch_ok"))
            ],
            "address_missing_count": sum(bool(x.get("fetch_ok")) and not x.get("address") for x in details),
            "description_missing_count": sum(bool(x.get("fetch_ok")) and not x.get("description_raw") for x in details),
            "reservation_info_count": sum(bool(x.get("reservation_info_present")) for x in details),
            "copyright_warning_count": sum(bool(x.get("copyright_warning_present")) for x in details),
            "explicit_offline_period_count": sum(bool(x.get("physical_period_source")) for x in details),
            "source_header_offline_period_conflict_count": sum(
                "source_header_offline_period_conflict" in (x.get("parse_warnings") or [])
                for x in details
            ),
            "non_seoul_detail_address_count": sum(
                "non_seoul_detail_address" in (x.get("parse_warnings") or []) for x in details
            ),
            "name_mismatch_count": sum(
                bool(x.get("fetch_ok"))
                and x.get("title_detail") != list_by_id.get(str(x["source_id"]), {}).get("name")
                for x in details
            ),
            "start_date_mismatch_count": sum(
                bool(x.get("fetch_ok"))
                and x.get("start_date_detail") != list_by_id.get(str(x["source_id"]), {}).get("start_date")
                for x in details
            ),
            "end_date_mismatch_count": sum(
                bool(x.get("fetch_ok"))
                and x.get("end_date_detail") != list_by_id.get(str(x["source_id"]), {}).get("end_date")
                for x in details
            ),
        }

    report = {
        "version": "1.0.0",
        "source": "popply",
        "run_timestamp": timestamp,
        "today": today.isoformat(),
        "candidate_count": len(enriched),
        "status_counts": status_counts,
        "source_status_mismatch_count": len(source_status_mismatches),
        "area_counts": dict(Counter(row["area_raw"] for row in enriched)),
        "crawl_diagnostics": diagnostics,
        "detail_fetch": detail_report,
        "collection_policy": {
            "scope": "public_rendered_pages_only",
            "low_frequency": True,
            "authentication_used": False,
            "private_api_used": False,
            "external_redistribution": "not_authorized_by_this_program",
        },
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[5/5] 결과 저장 완료")
    print()
    print("=== Popply v1.0.0 ===")
    print(f"서울 후보: {len(enriched)}건")
    print(f"상태: {status_counts}")
    if diagnostics.get("status_retry_counts"):
        print(f"상태 필터 재시도: {diagnostics.get('status_retry_counts')}")
        print(f"상태 간 ID 겹침률: {diagnostics.get('status_overlap_ratios')}")
        print(f"상태 필터 갱신 의심: {diagnostics.get('status_refresh_suspect_count', 0)}건")
    if detail_report:
        print(f"상세 성공/실패: {detail_report['success_count']} / {detail_report['failed_count']}")
        print(f"상세 캐시/live: {detail_report['cache_hit_count']} / {detail_report['live_fetch_count']}")
        print(
            f"상세 live 재시도/캐시복구: {detail_report['retried_live_count']} / "
            f"{detail_report['cache_recovery_count']}"
        )
        print(f"상세 핵심필드 불완전: {detail_report['core_detail_incomplete_count']}건")
        print(
            f"통합 사용/격리: {detail_report.get('integration_usable_count', len(enriched))} / "
            f"{detail_report.get('quarantine_count', 0)}"
        )
        if detail_report.get("quarantine_names"):
            preview = ", ".join(detail_report["quarantine_names"][:5])
            print(f"격리 항목: {preview}")
        print(f"상세 주소 누락: {detail_report['address_missing_count']}건")
        print(f"상세 설명 누락: {detail_report['description_missing_count']}건")
        print(
            "목록/상세 이름·시작일·종료일 불일치: "
            f"{detail_report['name_mismatch_count']} / "
            f"{detail_report['start_date_mismatch_count']} / "
            f"{detail_report['end_date_mismatch_count']}"
        )
        if detail_is_partial:
            print("부분 probe 결과이므로 3-source 자동 통합 입력으로 선택되지 않습니다.")
    print(f"실행 결과 폴더: {run_dir}")
    print("※ 공개 렌더링 페이지만 저빈도로 수집하며 외부 재배포 권한을 부여하지 않습니다.")


if __name__ == "__main__":
    main()
