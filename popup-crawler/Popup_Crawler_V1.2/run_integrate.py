from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from integration.classifier import classify_records
from integration.changes import build_daily_changes
from integration.common import SEOUL_TZ, common_records
from integration.decisions import apply_classification_decisions, apply_duplicate_decisions
from integration.duplicate import generate_duplicate_candidates, reject_redundant_review_edges
from integration.geocode import DEFAULT_CACHE_PATH, enrich_missing_coordinates
from integration.master import update_master
from integration.merge import build_canonical_preview
from integration.propagation import propagate_review_classifications
from storage.lifecycle import save_daily_views
from storage.csv_export import export_popup_csv
from utils.jsonl import load_jsonl, save_jsonl


def latest_file(pattern: str) -> Path:
    candidates = sorted(Path().glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"입력 파일을 찾지 못했습니다: {pattern}")
    return candidates[-1]


def optional_latest_file(pattern: str) -> Path | None:
    candidates = sorted(Path().glob(pattern))
    return candidates[-1] if candidates else None


DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT = 10
DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT = 25
DEFAULT_MAX_REVIEW_QUARANTINE_RATE = 0.08


def _env_path(name: str, fallback: str) -> Path:
    value = str(os.getenv(name) or "").strip()
    return Path(value) if value else Path(fallback)


def _review_record_ids(duplicate_review: list[dict]) -> set[str]:
    return {
        str(record_id)
        for item in duplicate_review
        for record_id in (item.get("left_record_id"), item.get("right_record_id"))
        if record_id
    }


def _source_refs_for_rows(rows: list[dict]) -> set[tuple[str, str]]:
    return {
        (str(row.get("source") or ""), str(row.get("source_id") or ""))
        for row in rows
        if row.get("source") and row.get("source_id") is not None
    }


def get_master_commit_block_reasons(
    classification_review: list[dict],
    duplicate_review: list[dict],
    canonical: list[dict],
    *,
    duplicate_quarantine_count: int | None = None,
    popup_record_count: int | None = None,
    max_classification_review_commit: int = DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT,
    max_duplicate_review_commit: int = DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT,
    max_review_quarantine_rate: float = DEFAULT_MAX_REVIEW_QUARANTINE_RATE,
) -> list[str]:
    """Block only on a review *spike*, not on ordinary daily ambiguity.

    Classification-review rows and duplicate-review components are quarantined
    out of today's backend snapshot. Matching old master rows are protected from
    false disappearance. Therefore a small review queue is safe to commit; only
    a large count/rate indicates a likely parser/source regression.
    """
    reasons: list[str] = []
    duplicate_quarantine_count = (
        len(_review_record_ids(duplicate_review))
        if duplicate_quarantine_count is None
        else duplicate_quarantine_count
    )
    apply_rate_gate = popup_record_count is not None
    effective_popup_count = popup_record_count or max(1, len(canonical) + duplicate_quarantine_count)

    if len(classification_review) > max_classification_review_commit:
        reasons.append(
            f"classification_quarantine={len(classification_review)} "
            f"> allowed={max_classification_review_commit}"
        )
    classification_rate = len(classification_review) / max(1, effective_popup_count)
    if apply_rate_gate and classification_review and classification_rate > max_review_quarantine_rate:
        reasons.append(
            f"classification_quarantine_rate={classification_rate:.1%} "
            f"> allowed={max_review_quarantine_rate:.1%}"
        )

    if duplicate_quarantine_count > max_duplicate_review_commit:
        reasons.append(
            f"duplicate_quarantine_records={duplicate_quarantine_count} "
            f"> allowed={max_duplicate_review_commit}"
        )
    duplicate_rate = duplicate_quarantine_count / max(1, effective_popup_count)
    if apply_rate_gate and duplicate_quarantine_count and duplicate_rate > max_review_quarantine_rate:
        reasons.append(
            f"duplicate_quarantine_rate={duplicate_rate:.1%} "
            f"> allowed={max_review_quarantine_rate:.1%}"
        )
    if not canonical:
        reasons.append("canonical_today_count=0")
    return reasons


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="v1.2 DayForYou + Popga + Popply production integration + persistent master + quarantine"
    )
    parser.add_argument("--popga", type=Path, help="Popga normalized_with_details.jsonl")
    parser.add_argument("--dayforyou", type=Path, help="DayForYou final_popup_db.jsonl")
    parser.add_argument("--popply", type=Path, help="Popply normalized_with_details.jsonl")
    parser.add_argument(
        "--decisions", type=Path, default=Path("config/review_decisions.jsonl"),
        help="검토 결정 JSONL",
    )
    parser.add_argument("--no-decisions", action="store_true", help="검토 결정을 적용하지 않음")
    parser.add_argument("--today", type=date.fromisoformat, help="검증 기준일 YYYY-MM-DD")
    parser.add_argument(
        "--master", type=Path, default=_env_path("POPUP_MASTER_PATH", "data/master/canonical_master.jsonl"),
        help="영구 canonical master 경로 (POPUP_MASTER_PATH 환경변수 지원)",
    )
    parser.add_argument(
        "--commit-master", action="store_true",
        help="검증된 master_candidate를 실제 master 파일로 반영",
    )
    parser.add_argument(
        "--allow-review-commit", action="store_true",
        help="분류/중복 REVIEW가 남아도 master 반영 허용(기본은 안전 차단)",
    )
    parser.add_argument(
        "--max-classification-review-commit", type=int,
        default=DEFAULT_MAX_CLASSIFICATION_REVIEW_COMMIT,
        help="격리 후 전체 반영을 계속 허용할 분류 검토 건수. 기본 10",
    )
    parser.add_argument(
        "--max-duplicate-review-commit", type=int,
        default=DEFAULT_MAX_DUPLICATE_REVIEW_COMMIT,
        help="격리 후 전체 반영을 계속 허용할 중복 관련 레코드 수. 기본 25",
    )
    parser.add_argument(
        "--max-review-quarantine-rate", type=float,
        default=float(os.getenv("POPUP_MAX_REVIEW_QUARANTINE_RATE", str(DEFAULT_MAX_REVIEW_QUARANTINE_RATE))),
        help="분류/중복 격리 비율이 이 값을 넘으면 전체 반영 차단. 기본 0.08",
    )
    parser.add_argument(
        "--no-geocode", action="store_true",
        help="Canonical 좌표 자동 보완을 비활성화",
    )
    parser.add_argument(
        "--geocode-cache", type=Path, default=DEFAULT_CACHE_PATH,
        help="Kakao 지오코딩 캐시 JSON 경로",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_classification_review_commit < 0:
        raise SystemExit("--max-classification-review-commit must be >= 0")
    if args.max_duplicate_review_commit < 0:
        raise SystemExit("--max-duplicate-review-commit must be >= 0")
    if not (0.0 <= args.max_review_quarantine_rate <= 1.0):
        raise SystemExit("--max-review-quarantine-rate must be between 0 and 1")
    popga_path = args.popga or latest_file("data/popga/runs/*/normalized_with_details.jsonl")
    dayforyou_path = args.dayforyou or latest_file("data/runs/*/final_popup_db.jsonl")
    popply_path = args.popply or optional_latest_file("data/popply/runs/*/normalized_with_details.jsonl")
    today = args.today or datetime.now(SEOUL_TZ).date()
    timestamp = datetime.now(SEOUL_TZ).strftime("%Y%m%d_%H%M%S")
    run_iso = datetime.now(SEOUL_TZ).isoformat(timespec="seconds")
    run_dir = Path("data/integration/runs") / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    print("[1/9] 실제 source 파일 안전 로드")
    popga_rows = load_jsonl(popga_path)
    dayforyou_rows = load_jsonl(dayforyou_path)
    popply_rows = load_jsonl(popply_path) if popply_path else []
    print(f"      Popga {len(popga_rows)} / DayForYou {len(dayforyou_rows)} / Popply {len(popply_rows)}")

    print("[2/9] 3-source 공통 schema 정규화")
    common = common_records(popga_rows, dayforyou_rows, popply_rows, today=today)

    print("[3/9] 공통 popup/non-popup 판정 + cross-source 전파")
    classified = classify_records(common)
    decisions = []
    if not args.no_decisions and args.decisions.exists():
        decisions = load_jsonl(args.decisions)
    classified, classification_decisions_applied = apply_classification_decisions(classified, decisions)
    classified, classification_propagations = propagate_review_classifications(classified)
    save_jsonl(classified, run_dir / "common_records.jsonl")

    popup_rows = [row for row in classified if row["classification"] == "POPUP"]
    non_popup_rows = [row for row in classified if row["classification"] == "NON_POPUP"]
    insufficient_rows = [row for row in classified if row["classification"] == "INSUFFICIENT_DATA"]
    classification_review = [
        row for row in classified if row["classification"] in {"REVIEW", "UNCERTAIN"}
    ]
    save_jsonl(non_popup_rows, run_dir / "non_popup_excluded.jsonl")
    save_jsonl(insufficient_rows, run_dir / "insufficient_data.jsonl")
    save_jsonl(classification_review, run_dir / "classification_review.jsonl")

    print("[4/9] source 간 중복 후보/자동병합 edge 생성")
    candidates = generate_duplicate_candidates(classified)
    candidates, duplicate_decisions_applied = apply_duplicate_decisions(candidates, decisions)
    candidates = reject_redundant_review_edges(candidates)
    save_jsonl(candidates, run_dir / "duplicate_candidates.jsonl")
    auto_edges = [item for item in candidates if item["decision"] == "AUTO_DUPLICATE"]
    duplicate_review = [item for item in candidates if item["decision"].startswith("REVIEW_")]
    save_jsonl(auto_edges, run_dir / "auto_duplicate_edges.jsonl")
    save_jsonl(duplicate_review, run_dir / "duplicate_review.jsonl")

    # Production rule: unresolved duplicate components are quarantined instead
    # of either publishing both sides as separate popups or blocking the entire
    # daily snapshot. Existing matching master rows are protected below.
    duplicate_review_ids = _review_record_ids(duplicate_review)
    duplicate_quarantine_rows = [
        row for row in classified
        if row.get("classification") == "POPUP" and row.get("record_id") in duplicate_review_ids
    ]
    save_jsonl(duplicate_quarantine_rows, run_dir / "duplicate_quarantine.jsonl")
    classified_for_canonical = [
        row for row in classified if row.get("record_id") not in duplicate_review_ids
    ]
    candidates_for_canonical = [
        item for item in candidates
        if item.get("left_record_id") not in duplicate_review_ids
        and item.get("right_record_id") not in duplicate_review_ids
    ]

    print("[5/9] provenance 포함 오늘 Canonical 생성 (REVIEW quarantine 제외)")
    canonical = build_canonical_preview(classified_for_canonical, candidates_for_canonical, today=today)
    save_jsonl(canonical, run_dir / "canonical_today_pre_geocode.jsonl")

    existing_master = load_jsonl(args.master) if args.master.exists() else []
    print("[6/9] Canonical 누락 좌표 보완")
    canonical, geocode_report, geocode_unresolved = enrich_missing_coordinates(
        canonical,
        cache_path=args.geocode_cache,
        reference_rows=existing_master,
        enabled=not args.no_geocode,
    )
    save_jsonl(canonical, run_dir / "canonical_today_pre_master.jsonl")
    save_jsonl(geocode_unresolved, run_dir / "geocode_unresolved.jsonl")
    (run_dir / "geocode_report.json").write_text(
        json.dumps(geocode_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[7/9] 영구 popup_id / master DB 후보 생성")
    retired_source_refs: set[tuple[str, str]] = set()
    for item in decisions:
        if item.get("decision_type") != "CLASSIFICATION" or item.get("classification") != "NON_POPUP":
            continue
        record_id = str(item.get("record_id") or "")
        if ":" not in record_id:
            continue
        source, source_id = record_id.split(":", 1)
        if source and source_id:
            retired_source_refs.add((source, source_id))

    # Small classification-review cases are intentionally skipped from today's
    # canonical. Protect matching old master rows from being falsely marked
    # absent/ended just because the source row was held for review.
    review_protected_source_refs = _source_refs_for_rows(classification_review)
    review_protected_source_refs |= _source_refs_for_rows(duplicate_quarantine_rows)

    master_candidate, master_report = update_master(
        canonical,
        existing_master,
        today=today,
        run_timestamp=run_iso,
        retired_source_refs=retired_source_refs,
        protected_source_refs=review_protected_source_refs,
    )
    save_jsonl(master_candidate, run_dir / "master_candidate.jsonl")
    current_with_ids = [row for row in master_candidate if row.get("seen_in_latest_run")]
    save_jsonl(current_with_ids, run_dir / "canonical_current.jsonl")

    change_report, change_buckets = build_daily_changes(existing_master, master_candidate)
    changes_dir = run_dir / "changes"
    changes_dir.mkdir(parents=True, exist_ok=True)
    for bucket_name, rows in change_buckets.items():
        save_jsonl(rows, changes_dir / f"{bucket_name}.jsonl")
    (run_dir / "daily_changes.json").write_text(
        json.dumps(change_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[8/9] ACTIVE / UPCOMING / ENDED / UNVERIFIED 분리")
    lifecycle_counts = save_daily_views(master_candidate, run_dir / "daily_views", today=today)

    master_committed = False
    backend_output_csv: str | None = None
    backend_output_count = 0
    master_commit_block_reasons = get_master_commit_block_reasons(
        classification_review, duplicate_review, canonical,
        duplicate_quarantine_count=len(duplicate_quarantine_rows),
        popup_record_count=len(popup_rows),
        max_classification_review_commit=args.max_classification_review_commit,
        max_duplicate_review_commit=args.max_duplicate_review_commit,
        max_review_quarantine_rate=args.max_review_quarantine_rate,
    )
    tolerated_classification_review_count = (
        len(classification_review)
        if 0 < len(classification_review) <= args.max_classification_review_commit
        else 0
    )
    tolerated_duplicate_review_count = (
        len(duplicate_review)
        if duplicate_review and not any(reason.startswith("duplicate_quarantine") for reason in master_commit_block_reasons)
        else 0
    )

    commit_allowed = (
        not master_commit_block_reasons or args.allow_review_commit
    )
    if args.commit_master and commit_allowed:
        # Stage the backend CSV before mutating master. If CSV serialization fails,
        # the trusted master remains untouched. Publish the staged file only after
        # master/views are safely written.
        output_csv = Path("output") / f"{today.strftime('%Y%m%d')}_popup.csv"
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        staged_csv = run_dir / f"{today.strftime('%Y%m%d')}_popup.csv.staged"
        backend_output_count = export_popup_csv(current_with_ids, staged_csv, target_date=today)

        args.master.parent.mkdir(parents=True, exist_ok=True)
        if args.master.exists():
            history_dir = args.master.parent / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.master, history_dir / f"{timestamp}_before.jsonl")
        save_jsonl(master_candidate, args.master)
        save_daily_views(master_candidate, args.master.parent / "views", today=today)
        (args.master.parent / ".popup_master_initialized").touch(exist_ok=True)
        master_committed = True

        staged_csv.replace(output_csv)
        backend_output_csv = str(output_csv)

    print("[9/9] audit/report 저장")
    decision_audit = [
        *classification_decisions_applied,
        *classification_propagations,
        *duplicate_decisions_applied,
    ]
    save_jsonl(decision_audit, run_dir / "review_decisions_applied.jsonl")

    sources = ["dayforyou", "popga", "popply"]
    source_classification_counts = {
        source: dict(Counter(row["classification"] for row in classified if row["source"] == source))
        for source in sources if any(row["source"] == source for row in classified)
    }
    decision_counts = dict(Counter(item["decision"] for item in candidates))
    merged_records = sum(len(item["source_refs"]) for item in canonical)
    multi_source_canonical = sum(len(item["sources"]) >= 2 for item in canonical)
    three_source_canonical = sum(len(item["sources"]) == 3 for item in canonical)
    inputs = {"popga": str(popga_path), "dayforyou": str(dayforyou_path)}
    if popply_path:
        inputs["popply"] = str(popply_path)
    input_counts = {
        "popga": len(popga_rows), "dayforyou": len(dayforyou_rows),
        "popply": len(popply_rows), "total": len(classified),
    }

    report = {
        "version": "1.2",
        "run_timestamp": timestamp,
        "today": today.isoformat(),
        "inputs": inputs,
        "input_counts": input_counts,
        "source_classification_counts": source_classification_counts,
        "classification_reason_counts": dict(Counter(
            reason for row in classified for reason in row.get("classification_reasons") or []
        )),
        "review_decision_file": str(args.decisions) if decisions else None,
        "classification_decisions_applied_count": len(classification_decisions_applied),
        "classification_propagations_count": len(classification_propagations),
        "duplicate_decisions_applied_count": len(duplicate_decisions_applied),
        "popup_record_count_before_merge": len(popup_rows),
        "non_popup_excluded_count": len(non_popup_rows),
        "insufficient_data_count": len(insufficient_rows),
        "classification_review_count": len(classification_review),
        "duplicate_candidate_count": len(candidates),
        "duplicate_decision_counts": decision_counts,
        "auto_duplicate_edge_count": len(auto_edges),
        "duplicate_review_count": len(duplicate_review),
        "duplicate_quarantine_record_count": len(duplicate_quarantine_rows),
        "duplicate_quarantine_file": str(run_dir / "duplicate_quarantine.jsonl"),
        "canonical_today_count": len(canonical),
        "geocoding": geocode_report,
        "multi_source_canonical_count": multi_source_canonical,
        "three_source_canonical_count": three_source_canonical,
        "source_records_in_canonical_count": merged_records,
        "popup_id_policy": "persistent_master_candidate",
        "master_path": str(args.master),
        "master_commit_requested": bool(args.commit_master),
        "master_committed": master_committed,
        "master_commit_block_reasons": master_commit_block_reasons,
        "review_commit_override": bool(args.allow_review_commit),
        "review_tolerance": {
            "max_classification_review_commit": args.max_classification_review_commit,
            "max_duplicate_review_commit": args.max_duplicate_review_commit,
            "tolerated_classification_review_count": tolerated_classification_review_count,
            "tolerated_duplicate_review_count": tolerated_duplicate_review_count,
            "duplicate_quarantine_record_count": len(duplicate_quarantine_rows),
            "max_review_quarantine_rate": args.max_review_quarantine_rate,
        },
        "master_update": master_report,
        "daily_changes": change_report,
        "lifecycle_counts": lifecycle_counts,
        "backend_output_csv": backend_output_csv,
        "backend_output_count": backend_output_count,
        "llm_calls": 0,
    }
    (run_dir / "run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print("=== v1.2 PRODUCTION integration + persistent master + review quarantine ===")
    print(f"공통 입력: {len(classified)}건 {input_counts}")
    print(f"source별 분류: {source_classification_counts}")
    print(f"POPUP {len(popup_rows)} / NON_POPUP {len(non_popup_rows)} / INSUFFICIENT {len(insufficient_rows)}")
    print(f"남은 분류 수동검토: {len(classification_review)}건")
    if tolerated_classification_review_count:
        print(
            f"분류 검토 {tolerated_classification_review_count}건: 이번 결과에서 제외하고 전체 반영은 계속"
        )
    print(
        f"자동병합 edge: {len(auto_edges)}건 / 남은 중복검토 edge: {len(duplicate_review)}건 / "
        f"격리 레코드: {len(duplicate_quarantine_rows)}건"
    )
    if tolerated_duplicate_review_count:
        print(
            f"중복 검토 {tolerated_duplicate_review_count} edge: 관련 {len(duplicate_quarantine_rows)}개 레코드를 "
            "오늘 출력에서 격리하고 안전 데이터 반영 계속"
        )
    print(f"오늘 Canonical: {len(canonical)}건")
    print(
        "좌표 보완: "
        f"누락 {geocode_report['missing_before']} → {geocode_report['missing_after']} / "
        f"채움 {geocode_report['filled_total']} "
        f"(캐시 {geocode_report['cache_hits']}, 동일주소 {geocode_report['same_address_reused']}, "
        f"Kakao주소 {geocode_report['kakao_address_filled']}, "
        f"Kakao키워드 {geocode_report['kakao_keyword_filled']})"
    )
    if geocode_report["enabled"] and not geocode_report["api_key_present"]:
        print("좌표 보완 API: KAKAO_REST_API_KEY 없음 - 캐시/동일주소 재사용만 수행")
    print(f"다중 source canonical: {multi_source_canonical}건 (3-source {three_source_canonical})")
    print(f"Persistent ID 재사용: {master_report['persistent_id_reused_count']} / 신규: {master_report['new_persistent_id_count']}")
    if master_report.get("retired_non_popup_count"):
        print(f"기존 Master 비팝업 확정 제거: {master_report['retired_non_popup_count']}건")
    print(f"Lifecycle: {lifecycle_counts}")
    print(
        "오늘 변화: "
        f"신규 {change_report['new_popup_count']} / "
        f"종료 {change_report['newly_ended_count']} / "
        f"재등장 {change_report['reappeared_count']} / "
        f"정보변경 {change_report['changed_popup_count']} / "
        f"미확인전환 {change_report['newly_unverified_count']}"
    )
    if args.commit_master and not master_committed:
        print(f"Master 반영: BLOCKED ({', '.join(master_commit_block_reasons)})")
    else:
        print(f"Master 반영: {'YES' if master_committed else 'NO (candidate only)'}")
    if backend_output_csv:
        print(f"Backend CSV: {backend_output_csv} ({backend_output_count}건)")
    print("LLM 호출: 0회")
    print(f"실행 결과 폴더: {run_dir}")
    if not args.commit_master:
        print("※ 결과 확인 후 같은 입력으로 --commit-master 를 붙이면 영구 master에 반영됩니다.")
    elif args.commit_master and not master_committed:
        print("※ REVIEW/빈 canonical 안전 게이트 때문에 master가 변경되지 않았습니다.")
        raise SystemExit(3)


if __name__ == "__main__":
    main()
