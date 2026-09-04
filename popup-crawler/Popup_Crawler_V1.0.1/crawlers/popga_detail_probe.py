from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SEOUL_TZ = ZoneInfo("Asia/Seoul")


def _select_probe_items(items: list[dict], count: int) -> list[dict]:
    """일반·오픈예정·종료일 미정 사례를 우선 포함한다."""
    selected: list[dict] = []
    seen: set[str] = set()

    def add(item: dict | None) -> None:
        if not item:
            return
        source_id = str(item.get("source_id") or "")
        if not source_id or source_id in seen or not item.get("detail_url"):
            return
        seen.add(source_id)
        selected.append(item)

    add(next(iter(items), None))
    add(next((x for x in items if x.get("source_status") == "오픈 예정"), None))
    add(next((x for x in items if x.get("end_date") is None), None))

    for item in items:
        if len(selected) >= count:
            break
        add(item)

    return selected[:count]


def probe_popga_details(
    items: list[dict],
    output_dir: str | Path,
    *,
    count: int = 5,
) -> dict:
    """공개 상세페이지 소수만 렌더링해 HTML/본문을 원문 그대로 보존한다."""
    if count <= 0:
        return {"requested_count": 0, "selected_count": 0, "records": []}

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("상세 probe 실행에는 playwright가 필요합니다.") from exc

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = _select_probe_items(items, count)
    pause_ms = int(float(os.getenv("POPGA_DETAIL_PAUSE", "1.0")) * 1000)
    headless = os.getenv("POPGA_HEADLESS", "true").strip().lower() not in {
        "0", "false", "no", "off"
    }
    records: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1200},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )

        for index, item in enumerate(selected, start=1):
            source_id = str(item["source_id"])
            detail_url = str(item["detail_url"])
            print(f"    [POPGA DETAIL {index}/{len(selected)}] {source_id}", end="")
            record = {
                "source": "popga",
                "source_id": source_id,
                "detail_url": detail_url,
                "fetch_ok": False,
                "http_status": None,
                "final_url": None,
                "page_title": None,
                "html_file": None,
                "text_file": None,
                "parse_warnings": [],
                "fetched_at": datetime.now(SEOUL_TZ).isoformat(timespec="seconds"),
            }

            try:
                response = page.goto(
                    detail_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_timeout(1800)
                html = page.content()
                body_text = page.locator("body").inner_text()
                html_name = f"{source_id}.html"
                text_name = f"{source_id}.txt"
                (output_dir / html_name).write_text(html, encoding="utf-8")
                (output_dir / text_name).write_text(body_text, encoding="utf-8")

                record.update({
                    "fetch_ok": True,
                    "http_status": response.status if response else None,
                    "final_url": page.url,
                    "page_title": page.title(),
                    "html_file": html_name,
                    "text_file": text_name,
                    "html_length": len(html),
                    "text_length": len(body_text),
                })
                if not body_text.strip():
                    record["parse_warnings"].append("body_text_empty")
                print(" - ok")
            except PlaywrightError as exc:
                record["parse_warnings"].append(
                    f"playwright_{exc.__class__.__name__}"
                )
                print(f" - fail ({exc.__class__.__name__})")

            records.append(record)
            if index < len(selected):
                page.wait_for_timeout(max(0, pause_ms))

        browser.close()

    report = {
        "requested_count": count,
        "selected_count": len(selected),
        "success_count": sum(bool(x["fetch_ok"]) for x in records),
        "failed_count": sum(not bool(x["fetch_ok"]) for x in records),
        "records": records,
    }
    (output_dir / "probe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
