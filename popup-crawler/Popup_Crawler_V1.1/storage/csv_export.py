from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from normalization.operation_hours import resolve_schedule_for_date

# Backend schema is not final yet. Keep a stable, explicit export surface so
# later mapping can be changed in one place without touching crawler/master data.
CSV_FIELDS = [
    "popup_id",
    "name",
    "brand",
    "category",
    "categories",
    "start_date",
    "end_date",
    "status",
    "venue_name",
    "address",
    "address_base",
    "district",
    "latitude",
    "longitude",
    "description",
    "reservation_required",
    "reservation_url",
    "official_url",
    "detail_url",
    "image_url",
    "tags",
    "operation_hours",
    "operation_hours_raw",
    "operation_schedule",
    "today_day",
    "today_schedule",
    "today_opening_time",
    "today_closing_time",
    "today_closed",
    "benefits",
    "website_links",
    "sources",
    "source_count",
    "source_refs",
    "confidence",
    "first_seen_at",
    "last_seen_at",
    "last_verified_at",
]

_JSON_FIELDS = {
    "categories",
    "tags",
    "operation_hours",
    "operation_hours_raw",
    "operation_schedule",
    "today_schedule",
    "benefits",
    "website_links",
    "source_refs",
}


def _csv_value(value: Any, *, field: str) -> Any:
    if value is None:
        return ""
    if field == "sources":
        if isinstance(value, (list, tuple, set)):
            return "|".join(str(x) for x in value if x not in (None, ""))
        return str(value)
    if field in _JSON_FIELDS or isinstance(value, (dict, list, tuple, set)):
        if isinstance(value, set):
            value = sorted(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def export_popup_csv(
    rows: Iterable[dict[str, Any]],
    path: str | Path,
    *,
    target_date: date | None = None,
) -> int:
    """Atomically export today's current canonical popup rows as UTF-8 BOM CSV.

    Only rows seen in the latest run and currently ACTIVE/UPCOMING are exported.
    Historical ENDED/UNVERIFIED rows remain in data/master and are intentionally
    excluded from the backend-facing daily snapshot.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target_date = target_date or date.today()

    selected = [
        row for row in rows
        if bool(row.get("seen_in_latest_run", True))
        and str(row.get("master_status") or row.get("status") or "") in {"ACTIVE", "UPCOMING"}
    ]
    selected.sort(key=lambda row: (
        str(row.get("start_date") or ""),
        str(row.get("name") or ""),
        str(row.get("popup_id") or ""),
    ))

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # utf-8-sig keeps Korean readable when the CSV is opened directly in Excel.
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in selected:
                sources = row.get("sources") or []
                day_fields = resolve_schedule_for_date(
                    list(row.get("operation_schedule") or []),
                    target_date,
                )
                out: dict[str, Any] = {}
                for field in CSV_FIELDS:
                    if field == "status":
                        value = row.get("master_status") or row.get("status")
                    elif field == "source_count":
                        value = len(sources) if isinstance(sources, (list, tuple, set)) else (1 if sources else 0)
                    elif field in day_fields:
                        value = day_fields[field]
                    else:
                        value = row.get(field)
                    out[field] = _csv_value(value, field=field)
                writer.writerow(out)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return len(selected)
