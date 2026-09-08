from __future__ import annotations

from typing import Any

from integration.duplicate import duplicate_features


def _strong_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    features = duplicate_features(left, right)
    if features["date_overlap_coverage"] <= 0:
        return False
    if (
        features["exact_core_name"]
        and features["exact_dates"]
        and (features["same_district"] or features["address_exact"])
    ):
        return True
    if (
        features["exact_core_name"]
        and left.get("start_date") == right.get("start_date")
        and features["date_overlap_coverage"] >= 0.5
        and (features["same_district"] or features["address_exact"])
    ):
        return True
    if (
        features["name_similarity"] >= 0.85
        and features["exact_dates"]
        and (features["same_district"] or features["address_exact"])
    ):
        return True
    return bool(
        features["address_exact"]
        and features["exact_dates"]
        and features["name_similarity"] >= 0.55
    )


def propagate_review_classifications(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """다른 source의 강한 동일행사 판정이 모두 같을 때 REVIEW에만 전파한다."""
    result = list(rows)
    applied: list[dict[str, Any]] = []

    for index, target in enumerate(result):
        if target.get("classification") != "REVIEW":
            continue
        evidence = [
            row for row in result
            if row.get("source") != target.get("source")
            and row.get("classification") in {"POPUP", "NON_POPUP"}
            and _strong_identity(target, row)
        ]
        classifications = {row["classification"] for row in evidence}
        if len(classifications) != 1:
            continue

        classification = classifications.pop()
        updated = dict(target)
        updated["classification_rule_before_cross_source"] = "REVIEW"
        updated["classification"] = classification
        updated["classification_reasons"] = [
            f"cross_source_strong_identity_{classification.lower()}"
        ]
        updated["classification_confidence"] = 0.97
        updated["classification_evidence"] = [
            {
                "record_id": row["record_id"],
                "source": row["source"],
                "classification": row["classification"],
            }
            for row in evidence
        ]
        result[index] = updated
        applied.append({
            "record_id": updated["record_id"],
            "before": "REVIEW",
            "after": classification,
            "evidence_record_ids": [row["record_id"] for row in evidence],
        })
    return result, applied
