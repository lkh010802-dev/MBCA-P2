from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from integration.duplicate import generate_duplicate_candidates
from integration.master import update_master
from run_integrate import _review_record_ids, _source_refs_for_rows, get_master_commit_block_reasons
from scripts.ensure_production_state import recover_from_csv


def row(source, sid, name, address, start, end, *, tags=None, description=""):
    district = address.split()[1] if address else ""
    return {
        "record_id": f"{source}:{sid}",
        "source": source,
        "source_id": sid,
        "name": name,
        "name_raw": name,
        "address": address,
        "address_base": address,
        "district": district,
        "start_date": start,
        "end_date": end,
        "classification": "POPUP",
        "official_url": None,
        "description": description,
        "tags": tags or [],
        "categories": [],
        "venue_name": None,
    }


class TodayDuplicateRegressionTests(unittest.TestCase):
    def test_amaimochi_alias_cluster_no_review(self):
        rows = [
            row("dayforyou", "36415", "[아마이모찌도넛 팝업]", "서울 영등포구 여의대로 108", "2026-08-21", "2026-09-15", tags=["모찌도넛", "보따리제과점", "아마이모찌도넛"], description="아마이모찌도넛 보따리제과점 새로운 모찌도넛 팝업"),
            row("popply", "5757", "아마이모찌도넛 팝업", "서울 영등포구 여의대로 108", "2026-08-21", "2026-09-15", tags=["모찌도넛", "보따리제과점", "아마이모찌도넛"], description="아마이모찌도넛 보따리제과점 모찌도넛 팝업"),
            row("popga", "8580", "아마이모찌도넛 팝업", "서울 영등포구 여의대로 108", "2026-08-21", "2026-09-15", tags=["모찌도넛", "보따리제과점", "아마이모찌도넛"], description="아마이모찌도넛 보따리제과점 새로운 팝업 모찌도넛"),
            row("dayforyou", "36418", "보따리제과점의 새로운 팝업,", "서울 영등포구 여의대로 108", "2026-08-21", "2026-09-15", tags=["bottaribakery", "모찌도넛", "보따리제과점"], description="보따리제과점의 새로운 팝업 아마이모찌도넛 모찌도넛"),
        ]
        candidates = generate_duplicate_candidates(rows)
        self.assertFalse(any(x["decision"].startswith("REVIEW_") for x in candidates))
        self.assertGreaterEqual(sum(x["decision"] == "AUTO_DUPLICATE" for x in candidates), 3)

    def test_conan_same_event_merges_but_unrelated_collab_cafe_rejects(self):
        conan = [
            row("dayforyou", "37529", "명탐정 코난 극장판 29기 콜라보 카페", "서울 마포구 양화로 188", "2026-08-13", "2026-09-20", tags=["극장판29기", "명탐정코난", "코난극장판"], description="명탐정 코난 극장판 29기 콜라보 카페"),
            row("popply", "5641", "명탐정 코난 콜라보 카페", "서울 마포구 양화로 188", "2026-08-13", "2026-09-20", tags=["극장판29기", "명탐정코난", "코난극장판"], description="명탐정 코난 극장판 29기 콜라보 카페"),
            row("popga", "8338", "명탐정 코난 X BOX cafe&space 콜라보 카페", "서울 마포구 양화로 188", "2026-08-13", "2026-09-20", tags=["극장판29기", "명탐정코난", "코난극장판"], description="명탐정 코난 BOX cafe space 극장판 29기"),
        ]
        unrelated = row("popga", "8620", "사한 X 모펀 콜라보 카페", "서울 마포구 양화로 188", "2026-08-28", "2026-09-20", tags=["콜라보카페"], description="사한 모펀 협업 카페")
        candidates = generate_duplicate_candidates([*conan, unrelated])
        self.assertFalse(any(x["decision"].startswith("REVIEW_") for x in candidates))
        conan_edges = [x for x in candidates if "8620" not in {x["left_source_id"], x["right_source_id"]}]
        self.assertTrue(conan_edges)
        self.assertTrue(all(x["decision"] == "AUTO_DUPLICATE" for x in conan_edges))
        unrelated_edges = [x for x in candidates if "8620" in {x["left_source_id"], x["right_source_id"]}]
        self.assertTrue(all(x["decision"].startswith("REJECT_") for x in unrelated_edges))

    def test_keroro_same_source_aliases_merge_different_street_instance_rejects(self):
        rows = [
            row("dayforyou", "37532", "개구리중사 케로로가 신촌에 떴다", "서울 서대문구 신촌로 83", "2026-08-28", "2026-09-14", tags=["개구리중사케로로", "케로로"], description="개구리중사 케로로 신촌 팝업"),
            row("dayforyou", "37188", "개구리 중사 케로로 팝업", "서울 서대문구 신촌로 83", "2026-08-28", "2026-09-14", tags=["개구리중사케로로", "케로로"], description="개구리 중사 케로로 신촌 팝업"),
            row("dayforyou", "36690", "개구리 중사 케로로 팝업이 신촌·용산에 동시에 뜬다", "서울 서대문구 신촌로 83", "2026-08-28", "2026-09-14", tags=["개구리중사케로로", "케로로"], description="개구리 중사 케로로 신촌 용산 팝업"),
            row("popga", "8502", "개구리 중사 케로로 팝업 @신촌", "서울 서대문구 연세로 13", "2026-08-28", "2026-09-14", tags=["개구리중사케로로", "케로로"], description="개구리 중사 케로로 신촌 팝업"),
        ]
        candidates = generate_duplicate_candidates(rows)
        self.assertFalse(any(x["decision"].startswith("REVIEW_") for x in candidates))
        same_address = [x for x in candidates if x.get("same_source_exact_identity")]
        self.assertGreaterEqual(len(same_address), 2)
        cross_address = [x for x in candidates if "8502" in {x["left_source_id"], x["right_source_id"]}]
        self.assertTrue(cross_address)
        self.assertTrue(all(x["decision"].startswith("REJECT_") for x in cross_address))


class QuarantineAndStateTests(unittest.TestCase):
    def test_review_quarantine_protects_old_master(self):
        review = [{"left_record_id": "popga:1", "right_record_id": "popply:2"}]
        ids = _review_record_ids(review)
        current_rows = [row("popga", "1", "A", "서울 강남구 테헤란로 1", "2026-09-01", "2026-09-30")]
        quarantined = [r for r in current_rows if r["record_id"] in ids]
        refs = _source_refs_for_rows(quarantined)
        old = {
            "popup_id": "popup_keep",
            "name": "A",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "source_refs": [{"source": "popga", "source_id": "1"}],
            "seen_in_latest_run": True,
            "missing_run_count": 0,
            "master_status": "ACTIVE",
        }
        result, report = update_master([], [old], today=date(2026, 9, 8), protected_source_refs=refs, run_timestamp="2026-09-08T11:00:00+09:00")
        self.assertEqual(1, len(result))
        self.assertEqual("popup_keep", result[0]["popup_id"])
        self.assertEqual(1, report["review_protected_master_count"])
        self.assertEqual(0, report["absent_from_latest_run_count"])

    def test_latest_csv_can_recover_persistent_ids_and_source_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_path = tmp / "20260907_popup.csv"
            target = tmp / "state" / "canonical_master.jsonl"
            fields = ["popup_id", "name", "start_date", "end_date", "status", "sources", "source_refs", "operation_schedule"]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "popup_id": "popup_abc",
                    "name": "테스트 팝업",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "status": "ACTIVE",
                    "sources": "popga|popply",
                    "source_refs": json.dumps([{"source": "popga", "source_id": "10"}, {"source": "popply", "source_id": "20"}], ensure_ascii=False),
                    "operation_schedule": "[]",
                })
            count = recover_from_csv(csv_path, target)
            self.assertEqual(1, count)
            restored = json.loads(target.read_text(encoding="utf-8").strip())
            self.assertEqual("popup_abc", restored["popup_id"])
            self.assertEqual(2, len(restored["source_refs"]))
            self.assertEqual("ACTIVE", restored["master_status"])
            self.assertTrue(restored["recovered_from_backend_csv"])

    def test_today_scale_13_edges_can_commit_when_only_small_quarantine(self):
        reviews = [
            {"left_record_id": f"a:{i}", "right_record_id": f"b:{i}"}
            for i in range(6)
        ] + [{"left_record_id": "a:0", "right_record_id": "c:0"}]
        # 13 edges can map to a small number of unique records; commit policy is
        # based on quarantined records/rate, not arbitrary edge count.
        reasons = get_master_commit_block_reasons(
            classification_review=[{}],
            duplicate_review=reviews,
            canonical=[{"popup_id": "safe"}],
            duplicate_quarantine_count=13,
            popup_record_count=579,
        )
        self.assertEqual([], reasons)


if __name__ == "__main__":
    unittest.main()
