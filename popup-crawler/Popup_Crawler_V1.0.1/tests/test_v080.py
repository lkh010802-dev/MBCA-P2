from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from integration.classifier import classify_popply
from integration.duplicate import generate_duplicate_candidates
from integration.master import update_master
from storage.lifecycle import lifecycle_status
from utils.jsonl import load_jsonl, save_jsonl


def row(source: str, source_id: str, name: str) -> dict:
    return {
        "record_id": f"{source}:{source_id}",
        "source": source,
        "source_id": source_id,
        "name": name,
        "name_raw": name,
        "address": "서울 송파구 올림픽로 240",
        "address_base": "서울 송파구 올림픽로 240",
        "district": "송파구",
        "start_date": "2026-07-31",
        "end_date": "2026-09-01",
        "category": "캐릭터/IP",
        "tags": [],
        "description": "",
        "classification": "POPUP",
        "last_verified_at": "2026-08-31T12:00:00+09:00",
        "first_seen_at": "2026-08-31T12:00:00+09:00",
        "last_seen_at": "2026-08-31T12:00:00+09:00",
        "source_refs": [{"source": source, "source_id": source_id}],
        "sources": [source],
    }


class V080Tests(unittest.TestCase):
    def test_jsonl_u2028_does_not_split_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.jsonl"
            save_jsonl([{"text": "a\u2028b"}, {"text": "c"}], path)
            loaded = load_jsonl(path)
            self.assertEqual(2, len(loaded))
            self.assertEqual("a\u2028b", loaded[0]["text"])

    def test_popply_permanent_cafe_is_non_popup(self) -> None:
        x = row("popply", "1", "폼폼푸린 베이커리 카페")
        x["start_date"] = "2026-07-28"
        x["end_date"] = "2026-08-31"
        x["description"] = "운영 기간 : 2026년 7월 28일 ~ 상시운영"
        self.assertEqual("NON_POPUP", classify_popply(x)["classification"])

    def test_popply_collab_cafe_body_is_popup(self) -> None:
        x = row("popply", "2", "Helluva Boss×애니메이트 카페")
        x["description"] = "#콜라보카페 개최! 콜라보 기간 7월31일~9월1일"
        self.assertEqual("POPUP", classify_popply(x)["classification"])

    def test_popply_short_popup_tag_is_popup(self) -> None:
        x = row("popply", "3", "PINGU x 롯데월드 아쿠아리움")
        x["start_date"] = "2026-07-04"
        x["end_date"] = "2026-08-31"
        x["description"] = "포토타임과 굿즈"
        x["tags"] = ["핑구팝업", "캐릭터팝업"]
        self.assertEqual("POPUP", classify_popply(x)["classification"])

    def test_popply_missing_long_description_is_insufficient(self) -> None:
        x = row("popply", "4", "올드페리도넛 성수")
        x["start_date"] = "2026-06-29"
        x["end_date"] = "2027-12-31"
        x["description"] = ""
        x["tags"] = ["도넛팝업"]
        self.assertEqual("INSUFFICIENT_DATA", classify_popply(x)["classification"])

    def test_popply_long_goods_store_is_non_popup(self) -> None:
        x = row("popply", "5", "Kpop 굿즈스토어")
        x["start_date"] = "2026-06-01"
        x["end_date"] = "2027-12-31"
        x["description"] = "성수에서 만날 수 있는 유일한 Kpop 굿즈스토어입니다."
        self.assertEqual("NON_POPUP", classify_popply(x)["classification"])

    def test_popply_immersive_theatre_is_non_popup(self) -> None:
        x = row("popply", "6", "STAY ALIVE IN MUSEUM")
        x["description"] = "박물관 전체를 돌아다니며 벌어지는 극한의 체험극"
        self.assertEqual("NON_POPUP", classify_popply(x)["classification"])

    def test_same_address_dates_shared_brand_tag_auto_merges(self) -> None:
        left = row("popga", "10", "헬로바 보스 X 애니메이트 콜라보 카페")
        right = row("popply", "11", "Helluva Boss×애니메이트 카페")
        left["tags"] = ["Helluva Boss", "잠실 팝업"]
        right["tags"] = ["Helluva Boss", "콜라보카페"]
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_core_containment_exact_place_dates_auto_merges(self) -> None:
        left = row("popga", "20", "더룩 팝업")
        right = row("popply", "21", "더 룩(The Look)")
        left["address"] = right["address"] = "서울 성동구 성수이로16길 5"
        left["address_base"] = right["address_base"] = "서울 성동구 성수이로16길 5"
        left["district"] = right["district"] = "성동구"
        left["start_date"] = right["start_date"] = "2026-08-14"
        left["end_date"] = right["end_date"] = "2026-09-13"
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_persistent_id_reused_on_next_run(self) -> None:
        current = row("popga", "100", "브랜드 팝업")
        current["source_refs"] = [{"source": "popga", "source_id": "100"}]
        first, report1 = update_master([current], [], today=date(2026, 8, 31), run_timestamp="2026-08-31T12:00:00+09:00")
        old_id = first[0]["popup_id"]
        newer = dict(current)
        newer["name"] = "브랜드 팝업 서울"
        second, report2 = update_master([newer], first, today=date(2026, 9, 1), run_timestamp="2026-09-01T12:00:00+09:00")
        self.assertEqual(old_id, second[0]["popup_id"])
        self.assertEqual(1, report2["persistent_id_reused_count"])


    def test_explicit_non_popup_decision_retires_old_master_row(self) -> None:
        current = row("popply", "4924", "진격의 거인展 FINAL 팝업")
        first, _ = update_master(
            [current], [], today=date(2026, 8, 31),
            run_timestamp="2026-08-31T12:00:00+09:00",
        )
        second, report = update_master(
            [], first, today=date(2026, 8, 31),
            run_timestamp="2026-08-31T13:00:00+09:00",
            retired_source_refs={("popply", "4924")},
        )
        self.assertEqual([], second)
        self.assertEqual(1, report["retired_non_popup_count"])
        self.assertEqual(0, report["unverified_absent_count"])

    def test_partial_retired_ref_does_not_delete_multi_source_master(self) -> None:
        current = row("popply", "4924", "공통 행사")
        current["source_refs"] = [
            {"source": "popply", "source_id": "4924"},
            {"source": "popga", "source_id": "9999"},
        ]
        current["sources"] = ["popga", "popply"]
        first, _ = update_master(
            [current], [], today=date(2026, 8, 31),
            run_timestamp="2026-08-31T12:00:00+09:00",
        )
        second, report = update_master(
            [], first, today=date(2026, 8, 31),
            run_timestamp="2026-08-31T13:00:00+09:00",
            retired_source_refs={("popply", "4924")},
        )
        self.assertEqual(1, len(second))
        self.assertEqual("UNVERIFIED", second[0]["master_status"])
        self.assertEqual(0, report["retired_non_popup_count"])

    def test_missing_open_ended_old_row_is_unverified(self) -> None:
        self.assertEqual(
            "UNVERIFIED",
            lifecycle_status("2026-01-01", None, today=date(2026, 8, 31), seen_in_latest_run=False),
        )


if __name__ == "__main__":
    unittest.main()
