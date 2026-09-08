from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm.popup_classifier import (
    classify_items,
    preview,
    save_jsonl,
    split_decisions,
)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def latest_run_dir() -> Path:
    candidates = sorted(
        [p for p in Path("data/runs").glob("*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("data/runs 아래 실행 결과가 없습니다.")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v1.0.0 LLM 후보만 후속 실행"
    )
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir or latest_run_dir()
    candidates = load_jsonl(run_dir / "llm_candidates.jsonl")
    auto_popup = load_jsonl(run_dir / "pre_llm_auto_popup.jsonl")
    auto_non_popup = load_jsonl(run_dir / "pre_llm_non_popup.jsonl")

    pv = preview(candidates)
    print(f"대상 run: {run_dir}")
    print(f"LLM 후보: {len(candidates)}건")
    print(f"모델: {pv['model']}")
    print(f"confidence 자동반영 기준: {pv['confidence_threshold']}")
    print(f"예상 API 호출: {pv['estimated_api_calls']}회")
    print(f".env API 키 감지: {'YES' if pv['api_key_present'] else 'NO'}")

    if not args.execute:
        print("DRY-RUN 종료: API 호출 0회")
        return

    if not candidates:
        save_jsonl(auto_popup, run_dir / "final_popup_db.jsonl")
        save_jsonl(
            auto_non_popup,
            run_dir / "final_non_popup_excluded.jsonl",
        )
        save_jsonl([], run_dir / "final_insufficient_data.jsonl")
        print("LLM 후보가 없어 API를 호출하지 않았습니다.")
        return

    decisions, meta = classify_items(candidates)
    (
        llm_popup,
        llm_non_popup,
        llm_insufficient,
        manual,
    ) = split_decisions(decisions)

    llm_dir = run_dir / "llm"
    save_jsonl(decisions, llm_dir / "llm_decisions.jsonl")
    save_jsonl(llm_popup, llm_dir / "llm_popup.jsonl")
    save_jsonl(llm_non_popup, llm_dir / "llm_non_popup.jsonl")
    save_jsonl(
        llm_insufficient,
        llm_dir / "llm_insufficient_data.jsonl",
    )
    save_jsonl(manual, llm_dir / "manual_review.jsonl")

    save_jsonl(
        auto_popup + llm_popup,
        run_dir / "final_popup_db.jsonl",
    )
    save_jsonl(
        auto_non_popup + llm_non_popup,
        run_dir / "final_non_popup_excluded.jsonl",
    )
    save_jsonl(
        llm_insufficient,
        run_dir / "final_insufficient_data.jsonl",
    )

    report = {
        **meta,
        "llm_popup": len(llm_popup),
        "llm_non_popup": len(llm_non_popup),
        "llm_insufficient_data": len(llm_insufficient),
        "manual_review": len(manual),
        "final_popup_count": len(auto_popup) + len(llm_popup),
        "final_non_popup_count": len(auto_non_popup) + len(llm_non_popup),
        "final_insufficient_data_count": len(llm_insufficient),
    }
    (llm_dir / "llm_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== LLM 실행 완료 ===")
    print(f"실제 API 호출: {meta['api_calls']}회")
    print(f"LLM POPUP: {len(llm_popup)}건")
    print(f"LLM NON_POPUP: {len(llm_non_popup)}건")
    print(f"LLM INSUFFICIENT_DATA: {len(llm_insufficient)}건")
    print(f"수동 검토 잔여: {len(manual)}건")


if __name__ == "__main__":
    main()
