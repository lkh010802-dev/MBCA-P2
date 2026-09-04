from __future__ import annotations

import unittest
from datetime import date

from integration.classifier import classify_dayforyou_final, classify_popga, classify_popply
from integration.decisions import apply_classification_decisions, apply_duplicate_decisions
from integration.duplicate import generate_duplicate_candidates
from integration.merge import build_canonical_preview
from integration.propagation import propagate_review_classifications


def record(
    source: str,
    source_id: str,
    name: str,
    *,
    address: str = "서울 송파구 올림픽로 300",
    start: str = "2026-08-16",
    end: str | None = "2026-08-31",
    classification: str = "POPUP",
) -> dict:
    return {
        "record_id": f"{source}:{source_id}",
        "source": source,
        "source_id": source_id,
        "name": name,
        "name_raw": name,
        "start_date": start,
        "end_date": end,
        "address": address,
        "address_base": address,
        "district": "송파구",
        "classification": classification,
        "last_verified_at": "2026-08-31T12:00:00+09:00",
        "first_seen_at": "2026-08-31T12:00:00+09:00",
        "last_seen_at": "2026-08-31T12:00:00+09:00",
        "source_url": None,
        "detail_url": None,
    }


class IntegrationTests(unittest.TestCase):
    def test_review_classification_propagates_only_from_strong_same_event(self) -> None:
        known = record("popga", "1", "드래곤볼 히어로즈 라이즈 서울")
        review = record("popply", "2", "드래곤볼 히어로즈 라이즈 서울", classification="REVIEW")
        changed, audit = propagate_review_classifications([known, review])
        self.assertEqual("POPUP", changed[1]["classification"])
        self.assertEqual(["popga:1"], audit[0]["evidence_record_ids"])

    def test_redundant_review_edge_is_removed_when_auto_path_exists(self) -> None:
        rows = [
            record("dayforyou", "1", "연도문구 팝업"),
            record("dayforyou", "2", "연도문구 팝업"),
            record("popga", "3", "연도문구 팝업"),
            record("popply", "4", "연도문구 팝업"),
        ]
        rows[-1]["address"] = None
        rows[-1]["address_base"] = None
        candidates = generate_duplicate_candidates(rows)
        self.assertFalse(any(x["decision"].startswith("REVIEW_") for x in candidates))
        canonical = build_canonical_preview(rows, candidates, today=date(2026, 8, 31))
        self.assertEqual(1, len(canonical))

    def test_popply_exhibition_category_is_non_popup(self) -> None:
        row = record("popply", "5602", "카린 X 타쿠 반나이 전시")
        row["category"] = "전시"
        row["description"] = "작품 전시"
        self.assertEqual("NON_POPUP", classify_popply(row)["classification"])

    def test_popply_explicit_popup_is_popup(self) -> None:
        row = record("popply", "5866", "올리브영 시티 로그 팝업")
        row["category"] = "뷰티/헬스"
        row["description"] = "콜라보 상품과 체험 공간"
        self.assertEqual("POPUP", classify_popply(row)["classification"])

    def test_review_decisions_are_audited(self) -> None:
        rows = [record("popga", "7022", "MGM IP UNIVERSE 2026", classification="REVIEW")]
        decisions = [{
            "decision_type": "CLASSIFICATION",
            "record_id": "popga:7022",
            "classification": "NON_POPUP",
            "reason": "human_review_general_exhibition",
        }]
        changed, audit = apply_classification_decisions(rows, decisions)
        self.assertEqual("NON_POPUP", changed[0]["classification"])
        self.assertEqual("REVIEW", audit[0]["before"])

    def test_keep_separate_decision_overrides_candidate(self) -> None:
        left = record("popga", "8326", "포켓몬 무릉도원 팝업")
        right = record("dayforyou", "35983", "포켓몬 30주년 팝업")
        candidates = generate_duplicate_candidates([left, right])
        decisions = [{
            "decision_type": "DUPLICATE",
            "left_record_id": left["record_id"],
            "right_record_id": right["record_id"],
            "decision": "KEEP_SEPARATE",
        }]
        changed, _ = apply_duplicate_decisions(candidates, decisions)
        self.assertEqual("REJECT_MANUAL_KEEP_SEPARATE", changed[0]["decision"])

    def test_three_source_triangle_remains_auto_merge(self) -> None:
        rows = [
            record("popga", "1", "같은 브랜드 팝업"),
            record("dayforyou", "2", "같은 브랜드 팝업"),
            record("popply", "3", "같은 브랜드 팝업"),
        ]
        candidates = generate_duplicate_candidates(rows)
        self.assertEqual(3, sum(x["decision"] == "AUTO_DUPLICATE" for x in candidates))
        canonical = build_canonical_preview(rows, candidates, today=date(2026, 8, 31))
        self.assertEqual(1, len(canonical))
        self.assertEqual(["dayforyou", "popga", "popply"], canonical[0]["sources"])

    def test_explicit_popup_title_overrides_non_store_event_type(self) -> None:
        row = record(
            "popga",
            "8406",
            "개구리 중사 케로로 X 건담베이스 팝업",
        )
        row["event_type_raw"] = "EVENT"
        row["description"] = "캐릭터 상품과 포토존"
        classified = classify_popga(row)
        self.assertEqual("POPUP", classified["classification"])

    def test_regular_exhibition_is_non_popup(self) -> None:
        row = record("popga", "8387", "Sol LeWitt: Open Structure 전시")
        row["event_type_raw"] = "EXHIBITION"
        row["description"] = "개념미술 전시"
        classified = classify_popga(row)
        self.assertEqual("NON_POPUP", classified["classification"])

    def test_dayforyou_promotion_is_rechecked(self) -> None:
        row = record(
            "dayforyou",
            "34658",
            "현대아울렛 하이디라오 BIG 할인 이벤트",
        )
        row["source_record_raw"] = {}
        classified = classify_dayforyou_final(row)
        self.assertEqual("NON_POPUP", classified["classification"])

    def test_exact_place_dates_do_not_merge_different_pokemon_events(self) -> None:
        popga = record("popga", "8326", "포켓몬 무릉도원 팝업")
        day = record(
            "dayforyou",
            "36334",
            "롯데타운 서머 마켓 포켓몬 별빛낙원",
        )
        candidates = generate_duplicate_candidates([popga, day])
        self.assertTrue(candidates)
        self.assertNotEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_same_mall_overlapping_dates_are_deterministically_rejected(self) -> None:
        popga = record(
            "popga",
            "8765",
            "비틀스 서울에디션 팝업 @더현대 서울",
            start="2026-09-04",
            end="2026-09-13",
        )
        day = record(
            "dayforyou",
            "27707",
            "버켄스탁 팝업 IN 더현대서울",
            start="2026-06-01",
            end="2026-09-30",
        )
        candidates = generate_duplicate_candidates([popga, day])
        self.assertEqual("REJECT_NOT_DUPLICATE", candidates[0]["decision"])

    def test_weaker_branch_candidate_is_rejected_after_auto_match(self) -> None:
        exact_branch = record(
            "popga", "8115", "티켓투더문 팝업 @청량리",
            address="서울 동대문구 왕산로 214",
            start="2026-07-16", end="2026-08-31",
        )
        other_branch = record(
            "popga", "8577", "티켓투더문 팝업",
            address="서울 중구 한강대로 405",
            start="2026-08-20", end="2026-09-02",
        )
        day = record(
            "dayforyou", "32075", "[티켓투더문] Pop-Up",
            address="서울 동대문구 왕산로 214",
            start="2026-07-16", end="2026-08-31",
        )
        candidates = generate_duplicate_candidates([exact_branch, other_branch, day])
        by_left = {item["left_source_id"]: item for item in candidates}
        self.assertEqual("AUTO_DUPLICATE", by_left["8115"]["decision"])
        self.assertEqual(
            "REJECT_CONFLICTS_WITH_AUTO_MATCH",
            by_left["8577"]["decision"],
        )

    def test_name_address_dates_create_auto_duplicate(self) -> None:
        popga = record("popga", "8657", "웃차 팝업")
        day = record("dayforyou", "36296", "5F 웃차 POP-UP")
        candidates = generate_duplicate_candidates([popga, day])
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_merge_preserves_sources_and_field_provenance(self) -> None:
        popga = record("popga", "8664", "샤넬 카페 마드모아젤 팝업")
        day = record("dayforyou", "36409", "샤넬 카페 마드모아젤 팝업")
        popga["description"] = "상세한 Popga 설명"
        candidates = generate_duplicate_candidates([popga, day])
        canonical = build_canonical_preview(
            [popga, day],
            candidates,
            today=date(2026, 8, 31),
        )
        self.assertEqual(1, len(canonical))
        self.assertEqual(["dayforyou", "popga"], canonical[0]["sources"])
        self.assertEqual(2, len(canonical[0]["source_refs"]))
        self.assertIn("name", canonical[0]["field_provenance"])
        self.assertTrue(canonical[0]["popup_id_is_preview"])


if __name__ == "__main__":
    unittest.main()
