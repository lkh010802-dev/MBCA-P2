from __future__ import annotations

from typing import Any


VALID_CLASSIFICATIONS = {"POPUP", "NON_POPUP", "INSUFFICIENT_DATA", "UNCERTAIN", "REVIEW"}
VALID_PAIR_DECISIONS = {"MERGE", "KEEP_SEPARATE"}


def _pair_key(left: object, right: object) -> tuple[str, str]:
    return tuple(sorted((str(left), str(right))))


def validate_decisions(decisions: list[dict[str, Any]]) -> None:
    seen_classification: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for index, item in enumerate(decisions, start=1):
        kind = item.get("decision_type")
        if kind == "CLASSIFICATION":
            record_id = str(item.get("record_id") or "")
            value = str(item.get("classification") or "")
            if not record_id or value not in VALID_CLASSIFICATIONS:
                raise ValueError(f"결정 파일 {index}행의 분류 결정이 잘못되었습니다")
            if record_id in seen_classification:
                raise ValueError(f"중복 분류 결정: {record_id}")
            seen_classification.add(record_id)
        elif kind == "DUPLICATE":
            left = str(item.get("left_record_id") or "")
            right = str(item.get("right_record_id") or "")
            value = str(item.get("decision") or "")
            if not left or not right or left == right or value not in VALID_PAIR_DECISIONS:
                raise ValueError(f"결정 파일 {index}행의 중복 결정이 잘못되었습니다")
            key = _pair_key(left, right)
            if key in seen_pairs:
                raise ValueError(f"중복 pair 결정: {key}")
            seen_pairs.add(key)
        else:
            raise ValueError(f"결정 파일 {index}행의 decision_type이 잘못되었습니다: {kind}")


def apply_classification_decisions(
    rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validate_decisions(decisions)
    by_id = {
        str(item["record_id"]): item
        for item in decisions
        if item["decision_type"] == "CLASSIFICATION"
    }
    applied: list[dict[str, Any]] = []
    result: list[dict[str, Any]] = []

    for row in rows:
        decision = by_id.get(str(row["record_id"]))
        if not decision:
            result.append(row)
            continue
        updated = dict(row)
        before = updated.get("classification")
        updated["classification_rule_before_review"] = before
        updated["classification"] = decision["classification"]
        updated["classification_reasons"] = [
            str(decision.get("reason") or "human_review_decision")
        ]
        updated["classification_confidence"] = 1.0
        updated["review_decision_applied"] = True
        result.append(updated)
        applied.append({
            "decision_type": "CLASSIFICATION",
            "record_id": updated["record_id"],
            "before": before,
            "after": updated["classification"],
            "reason": decision.get("reason"),
            "note": decision.get("note"),
        })

    return result, applied


def apply_duplicate_decisions(
    candidates: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validate_decisions(decisions)
    by_pair = {
        _pair_key(item["left_record_id"], item["right_record_id"]): item
        for item in decisions
        if item["decision_type"] == "DUPLICATE"
    }
    applied: list[dict[str, Any]] = []

    for candidate in candidates:
        key = _pair_key(candidate["left_record_id"], candidate["right_record_id"])
        item = by_pair.get(key)
        if not item:
            continue
        before = candidate["decision"]
        candidate["decision_before_review"] = before
        candidate["decision"] = (
            "AUTO_DUPLICATE" if item["decision"] == "MERGE"
            else "REJECT_MANUAL_KEEP_SEPARATE"
        )
        candidate["review_decision_applied"] = True
        candidate["review_note"] = item.get("note")
        applied.append({
            "decision_type": "DUPLICATE",
            "pair": list(key),
            "before": before,
            "after": candidate["decision"],
            "reason": item.get("reason"),
            "note": item.get("note"),
        })

    return candidates, applied
