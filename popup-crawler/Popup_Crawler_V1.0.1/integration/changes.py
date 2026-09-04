from __future__ import annotations

from collections import Counter
from typing import Any


TRACKED_FIELDS = (
    "name",
    "start_date",
    "end_date",
    "venue_name",
    "address",
    "address_base",
    "district",
    "category",
)


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row["popup_id"]): row
        for row in rows
        if row.get("popup_id")
    }


def _sources(row: dict[str, Any]) -> set[str]:
    values = row.get("sources") or []
    return {str(value) for value in values if value}


def _slim(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "popup_id": row.get("popup_id"),
        "name": row.get("name"),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "master_status": row.get("master_status"),
        "address": row.get("address"),
        "venue_name": row.get("venue_name"),
        "sources": sorted(_sources(row)),
        "seen_in_latest_run": row.get("seen_in_latest_run"),
    }


def build_daily_changes(
    existing_master: list[dict[str, Any]],
    proposed_master: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Compare the previous persistent master with the proposed daily master.

    The comparison is popup_id based, so re-running the same daily snapshot should
    produce zero changes after the first successful commit.
    """
    old_by_id = _index(existing_master)
    new_by_id = _index(proposed_master)

    new_popups: list[dict[str, Any]] = []
    newly_ended: list[dict[str, Any]] = []
    reappeared: list[dict[str, Any]] = []
    newly_unverified: list[dict[str, Any]] = []
    changed_popups: list[dict[str, Any]] = []
    source_changes: list[dict[str, Any]] = []
    retired_from_master: list[dict[str, Any]] = []

    for popup_id, current in new_by_id.items():
        old = old_by_id.get(popup_id)
        if old is None:
            if current.get("seen_in_latest_run"):
                new_popups.append(_slim(current))
            continue

        old_seen = bool(old.get("seen_in_latest_run", True))
        current_seen = bool(current.get("seen_in_latest_run"))
        old_status = str(old.get("master_status") or "")
        current_status = str(current.get("master_status") or "")

        if current_seen and (not old_seen or old_status in {"UNVERIFIED", "ENDED"}):
            reappeared.append({
                **_slim(current),
                "previous_master_status": old_status or None,
                "previous_seen_in_latest_run": old_seen,
            })

        if current_status == "ENDED" and old_status != "ENDED":
            newly_ended.append({
                **_slim(current),
                "previous_master_status": old_status or None,
            })

        if (
            current_status == "UNVERIFIED"
            and not current_seen
            and (old_seen or old_status != "UNVERIFIED")
        ):
            newly_unverified.append({
                **_slim(current),
                "previous_master_status": old_status or None,
            })

        changes: dict[str, dict[str, Any]] = {}
        if current_seen:
            for field in TRACKED_FIELDS:
                before = old.get(field)
                after = current.get(field)
                if before != after:
                    changes[field] = {"before": before, "after": after}
            if old_status != current_status:
                changes["master_status"] = {
                    "before": old_status or None,
                    "after": current_status or None,
                }
            if changes:
                changed_popups.append({
                    **_slim(current),
                    "changes": changes,
                })

        old_sources = _sources(old)
        current_sources = _sources(current)
        if current_seen and old_sources != current_sources:
            source_changes.append({
                **_slim(current),
                "sources_added": sorted(current_sources - old_sources),
                "sources_removed": sorted(old_sources - current_sources),
                "previous_sources": sorted(old_sources),
            })

    for popup_id, old in old_by_id.items():
        if popup_id not in new_by_id:
            retired_from_master.append(_slim(old))

    changed_field_counts = Counter(
        field
        for row in changed_popups
        for field in (row.get("changes") or {})
    )

    buckets = {
        "new_popups": new_popups,
        "newly_ended": newly_ended,
        "reappeared": reappeared,
        "newly_unverified": newly_unverified,
        "changed_popups": changed_popups,
        "source_changes": source_changes,
        "retired_from_master": retired_from_master,
    }
    sample_names = {
        name: [
            {"popup_id": row.get("popup_id"), "name": row.get("name")}
            for row in rows[:10]
        ]
        for name, rows in buckets.items()
    }

    report = {
        "previous_master_count": len(existing_master),
        "proposed_master_count": len(proposed_master),
        "new_popup_count": len(new_popups),
        "newly_ended_count": len(newly_ended),
        "reappeared_count": len(reappeared),
        "newly_unverified_count": len(newly_unverified),
        "changed_popup_count": len(changed_popups),
        "source_change_count": len(source_changes),
        "retired_from_master_count": len(retired_from_master),
        "changed_field_counts": dict(changed_field_counts),
        "samples": sample_names,
        "has_changes": any(bool(rows) for rows in buckets.values()),
    }
    return report, buckets
