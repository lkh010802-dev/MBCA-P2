from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from crawlers.popply_detail import (
    _read_valid_cached_record,
    _recover_cache_after_live_error,
    core_detail_complete,
    parse_detail_html,
)
from integration.classifier import classify_dayforyou_final, classify_popga, classify_popply
from integration.master import update_master
from run_daily import validate_popply


VALID_HTML = """
<html><head><meta property="og:image" content="https://example.com/a.jpg"></head><body>
<div class="popupdetail-title-info">
  <h1 class="tit">테스트 팝업</h1>
  <span class="calendar-store-category">패션</span>
  <span class="date">26.09.04 - 26.09.07</span>
  <div class="location">서울 성동구 동일로 79 ZZON <button>복사</button></div>
</div>
<div class="popupdetail-info-inner">테스트 팝업 설명</div>
</body></html>
"""

SKELETON_HTML = """
<html><body><div class="popupdetail-title-info"></div></body></html>
"""


class V094Tests(unittest.TestCase):
    def test_core_detail_requires_title_dates_and_address(self):
        broken = parse_detail_html(
            SKELETON_HTML, source_id="1", detail_url="https://popply.co.kr/popup/1"
        )
        good = parse_detail_html(
            VALID_HTML, source_id="1", detail_url="https://popply.co.kr/popup/1"
        )
        self.assertFalse(core_detail_complete(broken))
        self.assertTrue(core_detail_complete(good))

    def test_cache_search_skips_newer_skeleton_and_uses_older_valid_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            newer = root / "newer"
            older = root / "older"
            newer.mkdir(); older.mkdir()
            (newer / "1.html").write_text(SKELETON_HTML * 50, encoding="utf-8")
            (older / "1.html").write_text(VALID_HTML * 10, encoding="utf-8")
            now = time.time()
            os.utime(newer / "1.html", (now, now))
            os.utime(older / "1.html", (now - 60, now - 60))
            row = {
                "source_id": "1",
                "detail_url": "https://popply.co.kr/popup/1",
                "name": "테스트 팝업",
                "start_date": "2026-09-04",
                "end_date": "2026-09-07",
            }
            record, path, _age = _read_valid_cached_record(
                row, cache_dirs=[newer, older], cache_max_age_hours=54
            )
            self.assertIsNotNone(record)
            self.assertEqual(path, older / "1.html")
            self.assertEqual(record["address"], "서울 성동구 동일로 79")


    def test_live_error_can_recover_matching_valid_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            out = root / "out"
            cache.mkdir(); out.mkdir()
            (cache / "1.html").write_text(VALID_HTML * 10, encoding="utf-8")
            row = {
                "source_id": "1",
                "detail_url": "https://popply.co.kr/popup/1",
                "name": "테스트 팝업",
                "start_date": "2026-09-04",
                "end_date": "2026-09-07",
            }
            record = _recover_cache_after_live_error(
                row, cache_dirs=[cache], cache_max_age_hours=54,
                html_path=out / "1.html", live_attempts=1,
            )
            self.assertIsNotNone(record)
            self.assertTrue(record["cache_recovered_after_live_failure"])
            self.assertTrue(record["core_detail_complete"])
            self.assertTrue((out / "1.html").exists())

    def test_popply_core_incomplete_blocks_daily_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "normalized_with_details.jsonl").write_text("{}\n", encoding="utf-8")
            report = {
                "candidate_count": 10,
                "detail_fetch": {
                    "requested_count": 10,
                    "failed_count": 0,
                    "is_partial": False,
                    "core_detail_incomplete_count": 3,
                },
            }
            errors, _warnings, metrics = validate_popply(
                run_dir,
                report,
                previous_count=None,
                min_retention=0.65,
                min_source_count=1,
                max_detail_failure_rate=0.05,
            )
            self.assertTrue(any("core detail incomplete 3/10" in item for item in errors))
            self.assertEqual(metrics["detail_core_incomplete"], 3)

    def test_popply_festival_category_is_non_popup(self):
        row = {
            "name": "ODCF 2026",
            "description": "복합문화예술 행사",
            "category": "페스티벌",
            "tags": [],
            "start_date": "2026-09-19",
            "end_date": "2026-09-20",
        }
        self.assertEqual(classify_popply(row)["classification"], "NON_POPUP")

    def test_popga_festival_title_is_not_promoted_by_sub_popup_in_description(self):
        row = {
            "name": "2026 아덕페 - 아이파크몰 덕후 페스티벌",
            "description": "카드쇼와 하비쇼, 주술회전 X 리끌로우 팝업도 함께 열립니다.",
            "event_type_raw": "STORE",
            "start_date": "2026-10-02",
            "end_date": "2026-10-11",
        }
        result = classify_popga(row)
        self.assertEqual(result["classification"], "NON_POPUP")
        self.assertEqual(result["classification_reasons"], ["cultural_event_title"])


    def test_popga_exhibition_title_can_still_be_popup_when_detail_explicitly_says_popup(self):
        given = {
            "name": "기븐 전시",
            "description": "기븐展이 Pop Up Shop으로 Space Galleria에 오픈합니다.",
            "event_type_raw": "STORE",
            "start_date": "2026-08-29",
            "end_date": "2026-09-27",
        }
        lg = {
            "name": "LG전자 브랜드 전시 - THE FIRST : Origins",
            "description": 'LG전자 "THE FIRST : Origins" 헤리티지 전시 팝업',
            "event_type_raw": "STORE",
            "start_date": "2026-04-02",
            "end_date": "2026-12-31",
        }
        self.assertEqual(classify_popga(given)["classification"], "POPUP")
        self.assertEqual(classify_popga(lg)["classification"], "POPUP")

    def test_dayforyou_class_and_broken_title_are_not_auto_popup(self):
        base = {"source_record_raw": {}}
        class_row = {
            **base,
            "name": "The Best Class 앨리스 발레",
            "start_date": "2026-09-01",
            "end_date": "2026-11-30",
        }
        broken_row = {
            **base,
            "name": "장소: 주한 이탈리아 대사관저 (서울 용산구)",
            "start_date": "2026-09-01",
            "end_date": "2026-09-01",
        }
        self.assertEqual(classify_dayforyou_final(class_row)["classification"], "NON_POPUP")
        self.assertEqual(classify_dayforyou_final(broken_row)["classification"], "INSUFFICIENT_DATA")

    def test_master_tracks_current_sources_separately_from_ever_seen_sources(self):
        old = [{
            "popup_id": "popup_old",
            "name": "테스트 팝업",
            "start_date": "2026-09-01",
            "end_date": "2026-09-10",
            "address": "서울 성동구 연무장길 1",
            "address_base": "서울 성동구 연무장길 1",
            "district": "성동구",
            "source_refs": [
                {"source": "popga", "source_id": "10"},
                {"source": "popply", "source_id": "20"},
            ],
            "sources": ["popga", "popply"],
            "seen_in_latest_run": True,
            "master_status": "ACTIVE",
        }]
        current = [{
            "popup_id": "preview_x",
            "name": "테스트 팝업",
            "start_date": "2026-09-01",
            "end_date": "2026-09-10",
            "address": "서울 성동구 연무장길 1",
            "address_base": "서울 성동구 연무장길 1",
            "district": "성동구",
            "source_refs": [{"source": "popply", "source_id": "20"}],
            "sources": ["popply"],
        }]
        result, report = update_master(current, old, today=date(2026, 9, 2))
        row = next(item for item in result if item["popup_id"] == "popup_old")
        self.assertEqual(report["persistent_id_reused_count"], 1)
        self.assertEqual(row["sources"], ["popply"])
        self.assertEqual(row["sources_ever"], ["popga", "popply"])
        self.assertEqual(len(row["source_refs"]), 2)
        self.assertEqual(len(row["source_refs_current"]), 1)


if __name__ == "__main__":
    unittest.main()
