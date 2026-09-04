from __future__ import annotations

from datetime import date
from pathlib import Path

from utils.jsonl import save_jsonl


def lifecycle_status(
    start_date: str,
    end_date: str | None,
    *,
    today: date | None = None,
    seen_in_latest_run: bool = True,
) -> str:
    today = today or date.today()
    start = date.fromisoformat(start_date)

    if not seen_in_latest_run:
        if end_date and date.fromisoformat(end_date) < today:
            return "ENDED"
        return "UNVERIFIED"

    if start > today:
        return "UPCOMING"
    if end_date is None:
        return "ACTIVE"
    end = date.fromisoformat(end_date)
    if end < today:
        return "ENDED"
    return "ACTIVE"


def split_rows(
    rows: list[dict],
    *,
    today: date | None = None,
) -> dict[str, list[dict]]:
    groups = {
        "ACTIVE": [],
        "UPCOMING": [],
        "ENDED": [],
        "UNVERIFIED": [],
    }

    for row in rows:
        status = str(row.get("master_status") or lifecycle_status(
            str(row["start_date"]),
            str(row["end_date"]) if row.get("end_date") else None,
            today=today,
            seen_in_latest_run=bool(row.get("seen_in_latest_run", True)),
        ))
        item = dict(row)
        item["lifecycle_status"] = status
        groups.setdefault(status, []).append(item)

    return groups


def save_daily_views(
    rows: list[dict],
    output_dir: str | Path,
    *,
    today: date | None = None,
) -> dict[str, int]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    groups = split_rows(rows, today=today)
    filenames = {
        "ACTIVE": "active_now.jsonl",
        "UPCOMING": "upcoming.jsonl",
        "ENDED": "ended_archive.jsonl",
        "UNVERIFIED": "unverified.jsonl",
    }

    counts = {}
    for label, group in groups.items():
        save_jsonl(group, output_dir / filenames[label])
        counts[label] = len(group)
    return counts
