from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from crawlers.dayforyou import fetch_page, parse_popups, save_jsonl as save_raw_jsonl
from crawlers.dayforyou_detail import fetch_details
from normalization.dayforyou_normalizer import normalize_all
from normalization.review_classifier_v031 import classify_all
from llm.popup_classifier import classify_items, preview, save_jsonl, split_decisions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DayForYou 서울 팝업 전체 파이프라인 v1.0.0 component"
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="상세 HTML 공용 캐시를 쓰지 않고 이번 실행 전용으로 새로 요청",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="마지막 애매한 후보에 실제 OpenAI API 호출",
    )
    return parser.parse_args()


def save_rows(rows: list[dict], path: Path) -> None:
    save_jsonl(rows, path)


def enrich_review_item(item: dict, detail: dict | None) -> dict:
    out = dict(item)
    if not detail:
        out.update({
            "detail_fetch_ok": False,
            "detail_title": None,
            "detail_address": None,
            "detail_hashtags": [],
            "detail_summary": None,
            "detail_tip": None,
            "detail_parse_warnings": ["detail_missing"],
            "operation_hours": [],
            "operation_hours_raw": [],
        })
        return out

    out.update({
        "detail_fetch_ok": bool(detail.get("fetch_ok")),
        "detail_title": detail.get("title_detail"),
        "detail_address": detail.get("address_detail"),
        "detail_hashtags": detail.get("hashtags") or [],
        "detail_summary": detail.get("summary_text"),
        "detail_tip": detail.get("tip_text"),
        "official_url": detail.get("official_url"),
        "detail_parse_warnings": detail.get("parse_warnings") or [],
        "operation_hours": detail.get("operation_hours_raw") or [],
        "operation_hours_raw": detail.get("operation_hours_raw") or [],
        "detail_start_date": detail.get("start_date_detail"),
        "detail_end_date": detail.get("end_date_detail"),
    })

    if item.get("needs_data_review") and detail.get("address_detail"):
        out["address"] = detail["address_detail"]
        parts = detail["address_detail"].split()
        district = next((p for p in parts if p.endswith("구")), None)
        if district:
            out["district"] = district

    return out


def run_llm_stage(run_dir: Path, auto_popup: list[dict], auto_non_popup: list[dict], candidates: list[dict]) -> dict:
    llm_dir = run_dir / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)

    decisions, llm_meta = classify_items(candidates)
    llm_popup, llm_non_popup, llm_insufficient, manual = split_decisions(decisions)

    final_popup = auto_popup + llm_popup
    final_non_popup = auto_non_popup + llm_non_popup

    save_rows(decisions, llm_dir / "llm_decisions.jsonl")
    save_rows(llm_popup, llm_dir / "llm_popup.jsonl")
    save_rows(llm_non_popup, llm_dir / "llm_non_popup.jsonl")
    save_rows(llm_insufficient, llm_dir / "llm_insufficient_data.jsonl")
    save_rows(manual, llm_dir / "manual_review.jsonl")
    save_rows(final_popup, run_dir / "final_popup_db.jsonl")
    save_rows(final_non_popup, run_dir / "final_non_popup_excluded.jsonl")
    save_rows(llm_insufficient, run_dir / "final_insufficient_data.jsonl")

    return {
        **llm_meta,
        "llm_popup": len(llm_popup),
        "llm_non_popup": len(llm_non_popup),
        "llm_insufficient_data": len(llm_insufficient),
        "manual_review": len(manual),
        "final_popup_count": len(final_popup),
        "final_non_popup_count": len(final_non_popup),
    }


def main() -> None:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("data/runs") / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    print("[1/10] 오늘 기준 데이포유 전체 목록 새 요청")
    html, source_url = fetch_page()
    (run_dir / "dayforyou_all.html").write_text(html, encoding="utf-8")

    raw_items = parse_popups(html, source_url)
    save_raw_jsonl(raw_items, run_dir / "raw_seoul.jsonl")
    print(f"[2/10] 서울 RAW 저장: {len(raw_items)}건")

    normalized_objects = normalize_all(raw_items)
    normalized = [asdict(x) for x in normalized_objects]
    save_rows(normalized, run_dir / "normalized.jsonl")
    print(f"[3/10] 기본 정규화: {len(normalized)}건")

    review_items = [x for x in normalized if x.get("llm_review_candidate")]
    save_rows(review_items, run_dir / "detail_review_input.jsonl")
    print(f"[4/10] 상세 재검토 대상: {len(review_items)}건 / 운영시간 보강 대상: {len(normalized)}건")

    cache_dir = (
        run_dir / "detail_html"
        if args.fresh
        else Path("data/cache/detail_html")
    )
    # Operating hours live on DayForYou detail pages. Fetch/reparse every Seoul
    # card, not only ambiguous LLM-review candidates, so final backend records do
    # not lose published hours. Existing cache is reused when --fresh is absent.
    detail_records = fetch_details(normalized, cache_dir=cache_dir)
    details = [asdict(x) for x in detail_records]
    detail_by_id = {str(x["source_id"]): x for x in details}
    save_rows(details, run_dir / "details.jsonl")
    missing_hours_details = [x for x in details if not (x.get("operation_hours_raw") or [])]
    save_rows(missing_hours_details, run_dir / "operation_hours_missing_details.jsonl")
    print(
        f"[5/10] 상세 조회/파싱 완료: {len(details)}건 "
        f"(운영시간 확보 {len(details) - len(missing_hours_details)} / 미확보 {len(missing_hours_details)})"
    )

    enriched_all = [
        enrich_review_item(item, detail_by_id.get(str(item["source_id"])))
        for item in normalized
    ]
    enriched_review = [x for x in enriched_all if x.get("llm_review_candidate")]
    base_auto_popup = [x for x in enriched_all if not x.get("llm_review_candidate")]
    save_rows(enriched_review, run_dir / "detail_review_enriched.jsonl")
    save_rows(enriched_all, run_dir / "normalized_with_details.jsonl")

    classified = classify_all(enriched_review)
    rule_popup = [x for x in classified if x["v031_classification"] == "POPUP"]
    rule_non_popup = [x for x in classified if x["v031_classification"] == "NON_POPUP"]
    llm_candidates = [x for x in classified if x["v031_classification"] == "REVIEW"]
    print(f"[6/10] 상세 규칙 POPUP: {len(rule_popup)}건")
    print(f"[7/10] 상세 규칙 NON_POPUP: {len(rule_non_popup)}건")
    print(f"[8/10] 실제 LLM 후보: {len(llm_candidates)}건")

    auto_popup = base_auto_popup + rule_popup
    auto_non_popup = rule_non_popup
    save_rows(auto_popup, run_dir / "pre_llm_auto_popup.jsonl")
    save_rows(auto_non_popup, run_dir / "pre_llm_non_popup.jsonl")
    save_rows(llm_candidates, run_dir / "llm_candidates.jsonl")

    pv = preview(llm_candidates)
    (run_dir / "llm_preview.json").write_text(
        json.dumps(pv, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    llm_report = None
    if args.execute and llm_candidates:
        print("[9/10] OpenAI LLM 실제 호출 실행")
        llm_report = run_llm_stage(run_dir, auto_popup, auto_non_popup, llm_candidates)
    else:
        print("[9/10] DRY-RUN: OpenAI API 호출 0회")
        # 후보가 0건이면 LLM 실행 여부와 무관하게 결과가 완전히 결정된 상태다.
        # daily runner의 --no-llm 모드에서도 안전하게 사용할 수 있도록 최종 파일을 저장한다.
        if not llm_candidates:
            save_rows(auto_popup, run_dir / "final_popup_db.jsonl")
            save_rows(auto_non_popup, run_dir / "final_non_popup_excluded.jsonl")
            save_rows([], run_dir / "final_insufficient_data.jsonl")

    report = {
        "version": "1.0.1",
        "run_timestamp": timestamp,
        "fresh_detail_fetch": args.fresh,
        "seoul_total": len(normalized),
        "detail_review_input": len(review_items),
        "detail_enrichment_input": len(normalized),
        "operation_hours_found": sum(bool(x.get("operation_hours_raw")) for x in details),
        "operation_hours_missing": sum(not bool(x.get("operation_hours_raw")) for x in details),
        "detail_success": sum(bool(x.get("fetch_ok")) for x in details),
        "detail_failed": sum(not bool(x.get("fetch_ok")) for x in details),
        "address_missing_after_detail": sum(
            "address_missing" in (x.get("parse_warnings") or []) for x in details
        ),
        "base_auto_popup": len(base_auto_popup),
        "detail_rule_popup": len(rule_popup),
        "detail_rule_non_popup": len(rule_non_popup),
        "llm_candidate_count": len(llm_candidates),
        "llm_candidate_rate": round(len(llm_candidates) / len(normalized), 4) if normalized else 0,
        "llm_preview": pv,
        "llm_executed": bool(args.execute and llm_candidates),
        "llm_report": llm_report,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[10/10] 리포트 저장 완료")
    print()
    print("=== DayForYou v1.0.1 오늘자 전체 검증 결과 ===")
    print(f"서울 전체: {len(normalized)}건")
    print(f"상세 재검토 대상: {len(review_items)}건")
    print(f"상세 조회 성공/실패: {report['detail_success']} / {report['detail_failed']}")
    print(f"상세 주소 누락 경고: {report['address_missing_after_detail']}건")
    print(f"상세 규칙 팝업 자동확정: {len(rule_popup)}건")
    print(f"상세 규칙 비팝업 자동제외: {len(rule_non_popup)}건")
    print(f"최종 LLM 후보: {len(llm_candidates)}건 ({report['llm_candidate_rate'] * 100:.1f}%)")
    print(f"LLM 모델: {pv['model']}")
    print(f"예상 API 호출 횟수: {pv['estimated_api_calls']}회")
    print(f".env API 키 감지: {'YES' if pv['api_key_present'] else 'NO'}")

    if llm_report:
        print(f"LLM POPUP: {llm_report['llm_popup']}건")
        print(f"LLM NON_POPUP: {llm_report['llm_non_popup']}건")
        print(f"LLM INSUFFICIENT_DATA: {llm_report['llm_insufficient_data']}건")
        print(f"수동 검토 잔여: {llm_report['manual_review']}건")
        print(f"실제 API 호출: {llm_report['api_calls']}회")
    else:
        print("OpenAI API 실제 호출: 0회 (DRY-RUN)")
        print()
        print("후보 확인 후 같은 데이터를 LLM으로 판정하려면:")
        print(f"python run_llm.py --run-dir \"{run_dir}\" --execute")

    print(f"실행 결과 폴더: {run_dir}")


if __name__ == "__main__":
    main()
