from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JSON_FIELDS = {
    "categories", "tags", "operation_hours", "operation_hours_raw",
    "operation_schedule", "today_schedule", "benefits", "website_links",
    "source_refs",
}
BOOL_FIELDS = {"reservation_required", "today_closed"}
FLOAT_FIELDS = {"latitude", "longitude", "confidence"}
INT_FIELDS = {"source_count"}


def truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def master_path() -> Path:
    explicit = str(os.getenv("POPUP_MASTER_PATH") or "").strip()
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else ROOT / p
    state_dir = str(os.getenv("POPUP_STATE_DIR") or "").strip()
    if state_dir:
        p = Path(state_dir)
        if not p.is_absolute():
            p = ROOT / p
        return p / "canonical_master.jsonl"
    return ROOT / "data" / "master" / "canonical_master.jsonl"


def parse_bool(value: str) -> bool | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def parse_json(value: str, fallback: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def csv_row_to_master(raw: dict[str, str], now_iso: str) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in raw.items():
        if key in {"today_day", "today_schedule", "today_opening_time", "today_closing_time", "today_closed", "source_count"}:
            continue
        if key == "sources":
            row[key] = [x for x in str(value or "").split("|") if x]
        elif key in JSON_FIELDS:
            row[key] = parse_json(value, [] if key != "website_links" else {})
        elif key in BOOL_FIELDS:
            row[key] = parse_bool(value)
        elif key in FLOAT_FIELDS:
            text = str(value or "").strip()
            row[key] = float(text) if text else None
        elif key in INT_FIELDS:
            text = str(value or "").strip()
            row[key] = int(text) if text else 0
        else:
            row[key] = value if str(value or "") != "" else None

    status = str(raw.get("status") or "").strip() or "UNVERIFIED"
    refs = row.get("source_refs") or []
    sources = row.get("sources") or sorted({str(r.get("source")) for r in refs if r.get("source")})
    first_seen = row.get("first_seen_at") or now_iso
    last_seen = row.get("last_seen_at") or now_iso
    last_verified = row.get("last_verified_at") or last_seen
    row.update({
        "master_status": status,
        "source_refs": refs,
        "source_refs_current": refs,
        "sources": sources,
        "sources_ever": sources,
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "last_verified_at": last_verified,
        "master_created_at": first_seen,
        "master_updated_at": now_iso,
        "seen_in_latest_run": True,
        "missing_run_count": 0,
        "popup_id_is_preview": False,
        "persistent_id_reused": True,
        "recovered_from_backend_csv": True,
    })
    return row


def recover_from_csv(path: Path, target: Path) -> int:
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"popup_id", "name", "start_date", "status", "source_refs"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise RuntimeError(f"CSV cannot restore master; missing fields: {sorted(required - set(reader.fieldnames or []))}")
        for raw in reader:
            if not str(raw.get("popup_id") or "").strip():
                continue
            rows.append(csv_row_to_master(raw, now_iso))

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".recovering")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, target)
    return len(rows)


def latest_csv() -> Path | None:
    output_dir = ROOT / "output"
    if not output_dir.exists():
        return None
    rows = sorted(output_dir.glob("*_popup.csv"), key=lambda p: (p.name, p.stat().st_mtime))
    return rows[-1] if rows else None


def main() -> int:
    target = master_path().resolve()
    marker = target.parent / ".popup_master_initialized"
    local_master = (ROOT / "data" / "master" / "canonical_master.jsonl").resolve()

    if target.exists() and target.stat().st_size > 0:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
        print(f"[STATE] master OK: {target}")
        return 0

    # Migration path 1: a previous in-project master still exists.
    if local_master != target and local_master.exists() and local_master.stat().st_size > 0:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_master, target)
        marker.touch(exist_ok=True)
        print(f"[STATE] migrated existing master: {local_master} -> {target}")
        return 0

    # Migration path 2: recover persistent popup IDs/source refs from the latest
    # successful backend CSV. This is intentionally used only when the master is
    # absent, so it never overwrites a trusted master.
    csv_path = latest_csv()
    if csv_path is not None:
        count = recover_from_csv(csv_path, target)
        marker.touch(exist_ok=True)
        print(f"[STATE] recovered master from {csv_path.name}: {count} rows -> {target}")
        return 0

    if truthy("POPUP_ALLOW_MASTER_BOOTSTRAP"):
        target.parent.mkdir(parents=True, exist_ok=True)
        print("[STATE] no previous master/CSV; one-time bootstrap explicitly allowed")
        return 0

    print("[STATE ERROR] MASTER_STATE_MISSING", file=sys.stderr)
    print(f"No persistent master and no previous output CSV were found. Target: {target}", file=sys.stderr)
    print("Do not start production with an empty master by accident.", file=sys.stderr)
    print("For the first-ever bootstrap only, set POPUP_ALLOW_MASTER_BOOTSTRAP=1 for one run.", file=sys.stderr)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
