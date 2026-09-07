from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read JSONL by physical LF-delimited lines.

    Do not use str.splitlines(): valid JSON strings can contain Unicode line
    separators such as U+2028/U+2029, which splitlines() treats as a boundary.
    """
    path = Path(path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSONL parse error: {path} physical_line={line_no}: {exc}"
                ) from exc
    return rows


def save_jsonl(rows: Iterable[dict[str, Any]], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count
