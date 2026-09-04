from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field


Classification = Literal[
    "POPUP",
    "NON_POPUP",
    "INSUFFICIENT_DATA",
    "UNCERTAIN",
]


class PopupDecision(BaseModel):
    source_id: str
    classification: Classification
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class PopupDecisionBatch(BaseModel):
    decisions: list[PopupDecision]


SYSTEM_INSTRUCTIONS = """
너는 서울 오프라인 행사 데이터 정제용 분류기다.
제공된 데이터만 사용하고 외부 지식이나 추측으로 빈칸을 채우지 마라.

분류 기준:
- POPUP:
  기간 한정 팝업스토어, 브랜드 팝업, 팝업 전시/체험/콜라보 카페처럼
  명시적으로 팝업 성격이 있는 임시 오프라인 활성화.

- NON_POPUP:
  정보가 충분하고, 그 내용이 일반 상설 매장/신규 매장 오픈,
  사은품/상품권/쿠폰/멤버십/프로모션,
  일반 공연/연극/뮤지컬/전시/박람회/도서관/상설 체험/수강/대관 등이며
  팝업 성격이 아니라는 판단이 가능한 것.

- INSUFFICIENT_DATA:
  제목/설명/콘텐츠가 비어 있거나 플레이스홀더·템플릿 수준이라
  POPUP인지 NON_POPUP인지 판단할 실질적인 정보 자체가 부족한 것.
  예: "브랜드명 제품명 가격"처럼 실제 행사 설명이 없는 데이터.
  정보 부족을 NON_POPUP으로 억지 판정하지 마라.

- UNCERTAIN:
  실제 내용은 충분히 주어졌지만 POPUP과 NON_POPUP의 성격이 섞여 있거나
  제공 정보만으로 어느 쪽인지 자신 있게 구분하기 어려운 것.

중요:
1. 제목/설명/해시태그에 '팝업', 'POP-UP', 'POPUP'이 명시되면 강한 POPUP 근거다.
2. 단순히 기간이 짧다는 이유만으로 POPUP으로 분류하지 마라.
3. 특정 수집 사이트에 등록되었다는 사실만으로 POPUP이라고 가정하지 마라.
4. 데이터가 부실하면 INSUFFICIENT_DATA를 사용하라.
5. confidence는 해당 분류 자체에 대한 확신도이며 0~1 사이로 준다.
6. source_id를 입력 그대로 반환한다.
7. reason은 한 문장으로 짧게 쓴다.
""".strip()


def load_config() -> dict:
    load_dotenv()
    return {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
        "threshold": float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.85")),
        "batch_size": max(1, int(os.getenv("LLM_BATCH_SIZE", "10"))),
    }


def _short(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def compact_item(item: dict) -> dict:
    return {
        "source": item.get("source"),
        "source_id": str(item.get("source_id", "")),
        "name": _short(item.get("name"), 500),
        "address": _short(item.get("address"), 500),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
        "duration_days": item.get("duration_days"),
        "detail_title": _short(item.get("detail_title"), 500),
        "detail_summary": _short(item.get("detail_summary"), 1600),
        "detail_tip": _short(item.get("detail_tip"), 1800),
        "detail_hashtags": (item.get("detail_hashtags") or [])[:30],
        "rule_reasons": item.get("v031_classification_reasons") or [],
    }


def preview(items: list[dict]) -> dict:
    cfg = load_config()
    return {
        "candidate_count": len(items),
        "model": cfg["model"],
        "confidence_threshold": cfg["threshold"],
        "batch_size": cfg["batch_size"],
        "estimated_api_calls": (
            math.ceil(len(items) / cfg["batch_size"]) if items else 0
        ),
        "api_key_present": bool(cfg["api_key"]),
    }


def classify_items(items: list[dict]) -> tuple[list[dict], dict]:
    cfg = load_config()
    if not cfg["api_key"]:
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. 프로젝트 루트의 .env 파일에 키를 넣어주세요."
        )

    client = OpenAI(api_key=cfg["api_key"])
    by_id = {str(item["source_id"]): item for item in items}
    decisions: list[dict] = []
    calls = 0

    for start in range(0, len(items), cfg["batch_size"]):
        batch = items[start : start + cfg["batch_size"]]
        compact = [compact_item(x) for x in batch]
        payload = json.dumps(compact, ensure_ascii=False, indent=2)

        response = client.responses.parse(
            model=cfg["model"],
            instructions=SYSTEM_INSTRUCTIONS,
            input=(
                "다음 JSON 배열의 각 항목을 분류해라. "
                "모든 source_id에 대해 정확히 하나의 결정을 반환해야 한다.\n\n"
                + payload
            ),
            text_format=PopupDecisionBatch,
        )
        calls += 1

        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI 응답을 구조화된 결과로 파싱하지 못했습니다.")

        returned_ids = set()
        for decision in parsed.decisions:
            sid = str(decision.source_id)
            if sid not in by_id:
                continue

            returned_ids.add(sid)
            item = dict(by_id[sid])

            auto_applied = (
                decision.classification
                in {"POPUP", "NON_POPUP", "INSUFFICIENT_DATA"}
                and decision.confidence >= cfg["threshold"]
            )

            item.update({
                "llm_model": cfg["model"],
                "llm_classification": decision.classification,
                "llm_confidence": decision.confidence,
                "llm_reason": decision.reason,
                "llm_auto_applied": auto_applied,
            })
            decisions.append(item)

        missing = [
            str(x["source_id"])
            for x in batch
            if str(x["source_id"]) not in returned_ids
        ]
        if missing:
            raise RuntimeError(f"LLM 응답에서 source_id 누락: {missing}")

    meta = {
        "model": cfg["model"],
        "threshold": cfg["threshold"],
        "batch_size": cfg["batch_size"],
        "api_calls": calls,
        "candidate_count": len(items),
    }
    return decisions, meta


def split_decisions(
    decisions: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    popup: list[dict] = []
    non_popup: list[dict] = []
    insufficient: list[dict] = []
    manual: list[dict] = []

    for item in decisions:
        if not item.get("llm_auto_applied"):
            manual.append(item)
            continue

        label = item.get("llm_classification")
        if label == "POPUP":
            popup.append(item)
        elif label == "NON_POPUP":
            non_popup.append(item)
        elif label == "INSUFFICIENT_DATA":
            insufficient.append(item)
        else:
            manual.append(item)

    return popup, non_popup, insufficient, manual


def save_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
