from __future__ import annotations

import unittest

from integration.classifier import classify_dayforyou_final
from integration.duplicate import generate_duplicate_candidates


class FinalRoundupFilterTests(unittest.TestCase):
    def test_popup_roundup_title_is_not_a_place(self):
        row = {
            "record_id": "dayforyou:36652",
            "source": "dayforyou",
            "source_id": "36652",
            "name": "| 홍대 8월 4주차 팝업리스트",
            "name_raw": "| 홍대 8월 4주차 팝업리스트",
            "source_record_raw": {
                "detail_title": "| 홍대 8월 4주차 팝업리스트",
                "detail_summary": "[POP-UP LIST] 여러 팝업을 한 번에 소개합니다.",
            },
        }
        result = classify_dayforyou_final(row)
        self.assertEqual("NON_POPUP", result["classification"])
        self.assertEqual("popup_roundup_or_list_post", result["classification_reasons"][0])

    def test_single_popup_with_list_word_absent_stays_popup(self):
        row = {
            "record_id": "dayforyou:1",
            "source": "dayforyou",
            "source_id": "1",
            "name": "개구리 중사 케로로 팝업 @신촌",
            "name_raw": "개구리 중사 케로로 팝업 @신촌",
            "source_record_raw": {},
        }
        self.assertEqual("POPUP", classify_dayforyou_final(row)["classification"])


class StrongIdentityDuplicateTests(unittest.TestCase):
    def _row(
        self,
        source: str,
        source_id: str,
        name: str,
        *,
        address: str,
        start: str,
        end: str,
        description: str = "",
        official_url: str | None = None,
        tags: list[str] | None = None,
        district: str = "",
    ) -> dict:
        return {
            "record_id": f"{source}:{source_id}",
            "source": source,
            "source_id": source_id,
            "name": name,
            "name_raw": name,
            "address": address,
            "address_base": address,
            "district": district,
            "start_date": start,
            "end_date": end,
            "classification": "POPUP",
            "official_url": official_url,
            "description": description,
            "tags": tags or [],
            "categories": [],
            "venue_name": None,
        }

    def test_same_source_same_official_url_place_and_dates_merges(self):
        left = self._row(
            "dayforyou", "29948", "[라로제] Pop-Up Open",
            address="서울 노원구 동일로 1414",
            start="2026-06-26", end="2026-12-31",
            official_url="https://www.lotteshopping.com/shpgnews/shpgnewsDetail?shpgNewsNo=SNM00000000000539135",
        )
        right = self._row(
            "dayforyou", "31786", "[라로제] 스킨케어 Pop-Up",
            address="서울 노원구 동일로 1414",
            start="2026-06-26", end="2026-12-31",
            official_url="https://www.lotteshopping.com/shpgnews/shpgnewsDetail?shpgNewsNo=SNM00000000000539135",
        )
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual(1, len(candidates))
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])
        self.assertTrue(candidates[0]["official_url_exact"])

    def test_cross_source_alias_with_shared_brand_tag_and_body_merges(self):
        left = self._row(
            "popga", "8747", "REW 팝업",
            address="서울 강남구 압구정로 165",
            district="강남구",
            start="2026-09-04", end="2026-09-10",
            description="REW가 현대백화점 압구정본점에서 팝업을 선보입니다. 온라인에서 소개해온 REW의 컬렉션을 직접 입어보고 소재와 실루엣을 경험하실 수 있습니다.",
            tags=["REW", "패션", "압구정"],
        )
        right = self._row(
            "dayforyou", "37457", "[POP-UP STAGE] 리더블유",
            address="서울 강남구 압구정로 165",
            district="강남구",
            start="2026-09-04", end="2026-09-10",
            description="REW POP-UP REW가 현대백화점 압구정본점에서 팝업을 선보입니다. 온라인에서 소개해온 REW의 컬렉션을 직접 입어보고 소재와 실루엣을 경험하실 수 있는 자리를 준비했습니다.",
            tags=["RE.W", "패션팝업", "압구정"],
        )
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual(1, len(candidates))
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_cross_source_contained_brand_tag_merges(self):
        left = self._row(
            "popga", "8846", "DeÉpo X 키움히어로즈 팝업",
            address="서울 양천구 목동동로 257",
            district="양천구",
            start="2026-09-04", end="2026-09-13",
            description="DeÉpo x KIWOOM HEROES 팝업을 현대백화점 목동점에서 진행합니다. DeÉpo와 키움히어로즈가 함께 만든 특별한 컬렉션을 직접 만나보세요.",
            tags=["키움히어로즈", "DeÉpo", "패션"],
        )
        right = self._row(
            "dayforyou", "37505", "[POP-UP] 키움히어로즈 x 디에포",
            address="서울 양천구 목동동로 257",
            district="양천구",
            start="2026-09-04", end="2026-09-13",
            description="일상에서 만나는 영웅의 뜨거움 DeÉpo와 키움히어로즈가 함께 만든 특별한 컬렉션을 직접 만나보세요.",
            tags=["키움히어로즈x디에포", "패션"],
        )
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual(1, len(candidates))
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])
        self.assertGreaterEqual(candidates[0]["shared_distinctive_tag_count"], 1)

    def test_same_source_same_place_dates_with_multiple_shared_brand_tags_merges(self):
        left = self._row(
            "dayforyou", "36688", "NÜTRL × 트렌드랩 성수",
            address="서울 성동구 아차산로 104",
            district="성동구",
            start="2026-08-12", end="2026-09-13",
            description="NÜTRL × 트렌드랩 성수 팝업스토어 OPEN 보드카 베이스의 깔끔함 레몬의 톡 쏘는 맛",
            tags=["NUTRL", "OB맥주", "이마트24", "emart24"],
        )
        right = self._row(
            "dayforyou", "36687", "지금부터 스마일 업!",
            address="서울 성동구 아차산로 104",
            district="성동구",
            start="2026-08-12", end="2026-09-13",
            description="지금부터 스마일 업 NÜTRL X 트렌드랩 성수 팝업 구경하고 온 후기 보드카 레몬",
            tags=["NUTRL", "OB맥주", "이마트24", "emart24"],
        )
        candidates = generate_duplicate_candidates([left, right])
        self.assertEqual(1, len(candidates))
        self.assertEqual("AUTO_DUPLICATE", candidates[0]["decision"])

    def test_unrelated_events_same_place_and_dates_do_not_merge(self):
        left = self._row(
            "popga", "1", "브랜드 A 향수 팝업",
            address="서울 강남구 테헤란로 517",
            district="강남구",
            start="2026-09-01", end="2026-09-07",
            description="브랜드 A의 향수를 체험하는 행사입니다.",
            tags=["브랜드A", "향수"],
        )
        right = self._row(
            "dayforyou", "2", "브랜드 B 스포츠 팝업",
            address="서울 강남구 테헤란로 517",
            district="강남구",
            start="2026-09-01", end="2026-09-07",
            description="브랜드 B의 운동화를 만나보는 행사입니다.",
            tags=["브랜드B", "운동화"],
        )
        candidates = generate_duplicate_candidates([left, right])
        # It may appear as a rejected candidate if title similarity is high, but
        # must never be auto-merged or sent to manual review solely for sharing
        # a department-store address and dates.
        self.assertFalse(any(c["decision"] == "AUTO_DUPLICATE" for c in candidates))


if __name__ == "__main__":
    unittest.main()
