from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from typing import Any, Callable

from integration.common import derive_status
from integration.duplicate import core_name
from normalization.operation_hours import operation_fields


class UnionFind:
    def __init__(self, values: list[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _latest_key(row: dict[str, Any]) -> tuple[str, int]:
    source_rank = {"dayforyou": 1, "popply": 2, "popga": 3}
    return (
        str(row.get("last_verified_at") or ""),
        source_rank.get(str(row.get("source")), 0),
    )


def _select_name(rows: list[dict[str, Any]]) -> Any:
    values = [row for row in rows if row.get("name")]
    if not values:
        return None
    selected = max(
        values,
        key=lambda row: (
            len(core_name(row.get("name"))),
            {"dayforyou": 1, "popply": 2, "popga": 3}.get(
                str(row.get("source")), 0
            ),
            len(str(row.get("name"))),
        ),
    )
    return selected.get("name")


def _select_consensus_or_latest(
    rows: list[dict[str, Any]],
    field: str,
) -> Any:
    present = [row for row in rows if row.get(field) is not None]
    if not present:
        return None
    frozen = [str(row[field]) for row in present]
    counts = Counter(frozen)
    value, count = counts.most_common(1)[0]
    if count >= 2:
        return next(row[field] for row in present if str(row[field]) == value)
    return max(present, key=_latest_key).get(field)


def _select_richest(
    rows: list[dict[str, Any]],
    field: str,
) -> Any:
    present = [row for row in rows if row.get(field) not in (None, "", [], {})]
    if not present:
        return None
    return max(
        present,
        key=lambda row: (
            len(str(row.get(field))),
            _latest_key(row),
        ),
    ).get(field)


def _provenance(
    rows: list[dict[str, Any]],
    field: str,
    selected: Any,
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        value = row.get(field)
        if value in (None, "", [], {}):
            continue
        result.append({
            "source": row["source"],
            "source_id": row["source_id"],
            "value": value,
            "selected": value == selected,
        })
    return result


def _preview_id(rows: list[dict[str, Any]]) -> str:
    refs = "|".join(sorted(row["record_id"] for row in rows))
    digest = hashlib.sha256(refs.encode("utf-8")).hexdigest()[:16]
    return f"preview_{digest}"


def merge_cluster(
    rows: list[dict[str, Any]],
    *,
    today: date,
    duplicate_confidence: float | None,
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: row["record_id"])
    selectors: dict[str, Callable[[list[dict[str, Any]]], Any]] = {
        "name": _select_name,
        "start_date": lambda values: _select_consensus_or_latest(values, "start_date"),
        "end_date": lambda values: _select_consensus_or_latest(values, "end_date"),
    }
    rich_fields = [
        "brand", "category", "categories", "venue_name", "address",
        "address_base", "district", "latitude", "longitude", "description",
        "reservation_required", "reservation_url", "detail_url", "official_url",
        "image_url", "tags", "operation_hours", "benefits", "website_links",
    ]
    selected: dict[str, Any] = {}
    for field, selector in selectors.items():
        selected[field] = selector(rows)
    for field in rich_fields:
        selected[field] = _select_richest(rows, field)

    # Preserve the selected source wording and derive backend-friendly structure
    # only after canonical field selection so raw/schedule cannot come from
    # different sources.
    selected.update(operation_fields(selected.get("operation_hours") or []))

    start_date = str(selected["start_date"])
    end_date = str(selected["end_date"]) if selected.get("end_date") else None
    sources = sorted({str(row["source"]) for row in rows})
    first_seen_values = [row.get("first_seen_at") for row in rows if row.get("first_seen_at")]
    last_seen_values = [row.get("last_seen_at") for row in rows if row.get("last_seen_at")]
    verified_values = [row.get("last_verified_at") for row in rows if row.get("last_verified_at")]
    provenance_fields = ["name", "start_date", "end_date", *rich_fields]

    return {
        "popup_id": _preview_id(rows),
        **selected,
        "status": derive_status(start_date, end_date, today=today),
        "sources": sources,
        "source_refs": [
            {
                "source": row["source"],
                "source_id": row["source_id"],
                "detail_url": row.get("detail_url"),
                "source_url": row.get("source_url"),
            }
            for row in rows
        ],
        "confidence": (
            round(duplicate_confidence, 4)
            if duplicate_confidence is not None else 0.9
        ),
        "first_seen_at": min(first_seen_values) if first_seen_values else None,
        "last_seen_at": max(last_seen_values) if last_seen_values else None,
        "last_verified_at": max(verified_values) if verified_values else None,
        "field_provenance": {
            field: _provenance(rows, field, selected.get(field))
            for field in provenance_fields
            if _provenance(rows, field, selected.get(field))
        },
        "popup_id_is_preview": True,
    }


def build_canonical_preview(
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    today: date,
) -> list[dict[str, Any]]:
    popup_rows = [row for row in rows if row.get("classification") == "POPUP"]
    by_id = {row["record_id"]: row for row in popup_rows}
    union = UnionFind(list(by_id))
    auto_edges = [
        item for item in candidates
        if item.get("decision") == "AUTO_DUPLICATE"
        and item["left_record_id"] in by_id
        and item["right_record_id"] in by_id
    ]
    for edge in auto_edges:
        union.union(edge["left_record_id"], edge["right_record_id"])

    clusters: dict[str, list[dict[str, Any]]] = {}
    for record_id, row in by_id.items():
        clusters.setdefault(union.find(record_id), []).append(row)

    edge_scores: dict[str, list[float]] = {}
    for edge in auto_edges:
        root = union.find(edge["left_record_id"])
        edge_scores.setdefault(root, []).append(float(edge["duplicate_score"]) / 100.0)

    canonical = []
    for root, cluster in clusters.items():
        scores = edge_scores.get(root)
        confidence = min(scores) if scores else None
        canonical.append(
            merge_cluster(
                cluster,
                today=today,
                duplicate_confidence=confidence,
            )
        )
    canonical.sort(key=lambda item: (item["start_date"], item["name"] or ""))
    return canonical
