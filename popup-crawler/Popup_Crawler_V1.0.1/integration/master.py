from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from integration.common import derive_status
from integration.duplicate import duplicate_features


def _ref_key(ref: dict[str, Any]) -> tuple[str, str]:
    return (str(ref.get("source") or ""), str(ref.get("source_id") or ""))


def _source_ref_set(row: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        _ref_key(ref)
        for ref in (row.get("source_refs") or [])
        if ref.get("source") and ref.get("source_id") is not None
    }


def _initial_popup_id(row: dict[str, Any]) -> str:
    refs = sorted(_source_ref_set(row))
    seed_parts = [f"{source}:{source_id}" for source, source_id in refs]
    if not seed_parts:
        seed_parts = [
            str(row.get("name") or ""),
            str(row.get("address_base") or row.get("address") or ""),
            str(row.get("start_date") or ""),
        ]
    digest = hashlib.sha256("|".join(seed_parts).encode("utf-8")).hexdigest()[:16]
    return f"popup_{digest}"


def _merge_source_refs(old: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in [*(old.get("source_refs") or []), *(current.get("source_refs") or [])]:
        key = _ref_key(ref)
        if not all(key):
            continue
        previous = merged.get(key, {})
        merged[key] = {**previous, **ref}
    return [merged[key] for key in sorted(merged)]


def _candidate_match_score(current: dict[str, Any], old: dict[str, Any]) -> float:
    current_refs = _source_ref_set(current)
    old_refs = _source_ref_set(old)
    ref_overlap = len(current_refs & old_refs)
    if ref_overlap:
        return 1000.0 + 100.0 * ref_overlap

    features = duplicate_features(current, old)
    if features["date_overlap_coverage"] <= 0:
        return -1.0

    # Conservative identity rescue when source IDs changed or a source vanished.
    if (
        features["address_exact"]
        and features["exact_dates"]
        and features["name_similarity"] >= 0.55
    ):
        return 300.0 + float(features["duplicate_score"])
    if (
        features["exact_core_name"]
        and features["date_overlap_coverage"] >= 0.8
        and (features["address_exact"] or features["same_district"])
    ):
        return 250.0 + float(features["duplicate_score"])
    if (
        features["address_exact"]
        and features["date_overlap_coverage"] >= 0.8
        and features["name_similarity"] >= 0.72
    ):
        return 200.0 + float(features["duplicate_score"])
    return -1.0


def _status_for_absent(row: dict[str, Any], *, today: date) -> str:
    end_date = row.get("end_date")
    if end_date and date.fromisoformat(str(end_date)) < today:
        return "ENDED"
    return "UNVERIFIED"


def _update_matched(
    old: dict[str, Any],
    current: dict[str, Any],
    *,
    today: date,
    run_timestamp: str,
) -> dict[str, Any]:
    merged_refs = _merge_source_refs(old, current)
    first_seen_values = [
        value for value in (old.get("first_seen_at"), current.get("first_seen_at"))
        if value
    ]
    current_refs = list(current.get("source_refs") or [])
    current_sources = sorted({
        str(ref.get("source")) for ref in current_refs if ref.get("source")
    } or {str(x) for x in (current.get("sources") or []) if x})
    sources_ever = sorted(
        {str(x) for x in (old.get("sources_ever") or old.get("sources") or []) if x}
        | set(current_sources)
    )
    result = dict(current)
    result.update({
        "popup_id": old["popup_id"],
        "popup_id_is_preview": False,
        "persistent_id_reused": True,
        # source_refs는 persistent identity를 위해 누적 보존한다.
        "source_refs": merged_refs,
        # 현재 source와 역대 source를 분리해 daily source 변화가 실제로 보이게 한다.
        "source_refs_current": current_refs,
        "sources": current_sources,
        "sources_ever": sources_ever,
        "first_seen_at": min(first_seen_values) if first_seen_values else None,
        "last_seen_at": current.get("last_seen_at") or run_timestamp,
        "last_verified_at": current.get("last_verified_at") or run_timestamp,
        "master_created_at": old.get("master_created_at") or run_timestamp,
        "master_updated_at": run_timestamp,
        "seen_in_latest_run": True,
        "missing_run_count": 0,
        "master_status": derive_status(
            str(current["start_date"]),
            str(current["end_date"]) if current.get("end_date") else None,
            today=today,
        ),
    })
    return result


def _new_master_row(
    current: dict[str, Any],
    *,
    today: date,
    run_timestamp: str,
) -> dict[str, Any]:
    result = dict(current)
    current_refs = list(current.get("source_refs") or [])
    current_sources = sorted({
        str(ref.get("source")) for ref in current_refs if ref.get("source")
    } or {str(x) for x in (current.get("sources") or []) if x})
    result.update({
        "popup_id": _initial_popup_id(current),
        "popup_id_is_preview": False,
        "persistent_id_reused": False,
        "source_refs_current": current_refs,
        "sources": current_sources,
        "sources_ever": current_sources,
        "master_created_at": run_timestamp,
        "master_updated_at": run_timestamp,
        "seen_in_latest_run": True,
        "missing_run_count": 0,
        "master_status": derive_status(
            str(current["start_date"]),
            str(current["end_date"]) if current.get("end_date") else None,
            today=today,
        ),
    })
    return result


def update_master(
    current_canonical: list[dict[str, Any]],
    existing_master: list[dict[str, Any]],
    *,
    today: date,
    run_timestamp: str | None = None,
    retired_source_refs: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a proposed persistent master without writing files.

    Exact source refs are indexed first, so normal daily runs reuse IDs in
    near-linear time. Only records without a source-ref match enter the more
    expensive identity-rescue comparison.
    """
    run_timestamp = run_timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
    retired_source_refs = retired_source_refs or set()
    old_by_id = {str(row["popup_id"]): row for row in existing_master if row.get("popup_id")}

    ref_index: dict[tuple[str, str], set[str]] = {}
    for old_id, old in old_by_id.items():
        for ref in _source_ref_set(old):
            ref_index.setdefault(ref, set()).add(old_id)

    matched_current: dict[int, str] = {}
    used_old: set[str] = set()

    # Pass 1: exact source-reference identity.
    for index, current in enumerate(current_canonical):
        votes: dict[str, int] = {}
        for ref in _source_ref_set(current):
            for old_id in ref_index.get(ref, set()):
                votes[old_id] = votes.get(old_id, 0) + 1
        if not votes:
            continue
        ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
        for old_id, _count in ranked:
            if old_id not in used_old:
                matched_current[index] = old_id
                used_old.add(old_id)
                break

    # Pass 2: conservative rescue only for the small unmatched subset.
    unmatched_current = [
        (index, row) for index, row in enumerate(current_canonical)
        if index not in matched_current
    ]
    unmatched_old = [
        (old_id, row) for old_id, row in old_by_id.items()
        if old_id not in used_old
    ]
    possible: list[tuple[float, int, str]] = []
    for index, current in unmatched_current:
        for old_id, old in unmatched_old:
            score = _candidate_match_score(current, old)
            if score >= 0:
                possible.append((score, index, old_id))
    possible.sort(reverse=True)

    for score, index, old_id in possible:
        if index in matched_current or old_id in used_old:
            continue
        matched_current[index] = old_id
        used_old.add(old_id)

    result: list[dict[str, Any]] = []
    new_count = 0
    reused_count = 0
    for index, current in enumerate(current_canonical):
        old_id = matched_current.get(index)
        if old_id:
            result.append(_update_matched(
                old_by_id[old_id], current,
                today=today, run_timestamp=run_timestamp,
            ))
            reused_count += 1
        else:
            result.append(_new_master_row(
                current, today=today, run_timestamp=run_timestamp,
            ))
            new_count += 1

    absent_count = 0
    ended_from_absence = 0
    unverified_count = 0
    retired_non_popup_count = 0
    for old_id, old in old_by_id.items():
        if old_id in used_old:
            continue
        old_refs = _source_ref_set(old)
        # Human classification corrections can retire a previously accepted
        # canonical row. Only remove it when *all* of its known source refs
        # are explicitly retired, so a valid multi-source popup is never
        # deleted because one source changed classification.
        if old_refs and old_refs.issubset(retired_source_refs):
            retired_non_popup_count += 1
            continue
        absent = dict(old)
        absent["seen_in_latest_run"] = False
        absent["missing_run_count"] = int(old.get("missing_run_count") or 0) + 1
        absent["master_updated_at"] = run_timestamp
        absent["master_status"] = _status_for_absent(absent, today=today)
        result.append(absent)
        absent_count += 1
        if absent["master_status"] == "ENDED":
            ended_from_absence += 1
        else:
            unverified_count += 1

    ids = [str(row["popup_id"]) for row in result]
    if len(ids) != len(set(ids)):
        raise ValueError("persistent popup_id collision detected")

    result.sort(key=lambda row: (str(row.get("start_date") or ""), str(row.get("name") or "")))
    report = {
        "existing_master_count": len(existing_master),
        "current_canonical_count": len(current_canonical),
        "persistent_id_reused_count": reused_count,
        "new_persistent_id_count": new_count,
        "absent_from_latest_run_count": absent_count,
        "ended_from_absence_count": ended_from_absence,
        "unverified_absent_count": unverified_count,
        "retired_non_popup_count": retired_non_popup_count,
        "proposed_master_count": len(result),
    }
    return result, report
