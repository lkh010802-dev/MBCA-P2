from __future__ import annotations

import json
import unittest

from crawlers.popga_detail import (
    extract_embedded_popup_payload,
    parse_detail_html,
)
from run_popga import enrich_with_details


def build_html(payload: dict) -> str:
    flight = [
        "$",
        "$L2a",
        None,
        {"state": {"data": {"data": payload}}},
    ]
    chunk = "9:" + json.dumps(flight, ensure_ascii=False) + "\n"
    outer = json.dumps([1, chunk], ensure_ascii=False)
    return f"<html><body><script>self.__next_f.push({outer})</script></body></html>"


class PopgaDetailParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "id": 8784,
            "type": "STORE",
            "files": [
                {
                    "path": "https://cdn.popga.co.kr/second.webp",
                    "sequence": 2,
                },
                {
                    "path": "https://cdn.popga.co.kr/main.webp",
                    "sequence": 1,
                },
            ],
            "title": "포켓몬 포코피아 컨셉스토어",
            "subTitle": "",
            "content": "원천 소개 문구",
            "aiSupplement": "원천 사이트 AI 요약",
            "categories": [
                {"id": 40, "name": "애니/캐릭터"},
                {"id": 7, "name": "캐릭터"},
            ],
            "tags": ["성수", "사전 예약"],
            "periodType": "READY",
            "openDate": "2026-09-12",
            "closeDate": "2026-09-29",
            "operationTime": ["매일 11:00 ~ 22:00"],
            "latitude": 37.5403,
            "longitude": 127.0557,
            "address": "서울 성동구 성수이로 62 (성수동2가)",
            "addressDetail": "무신사 메가스토어 성수 1층",
            "roadAddress": "서울 성동구 성수이로 62",
            "website": {
                "instagram": "https://www.instagram.com/example",
            },
            "preReservationStartedAt": "2026-09-04T18:00:00",
            "preReservationEndedAt": None,
            "preReservationLink": None,
            "isPopgaReservation": False,
            "benefits": [
                {"key": "방문", "value": ""},
                {"key": "구매 고객", "value": "사은품 증정"},
            ],
            "additionalInformation": "📷 instagram @example",
            "notice": "",
            "ageRestrictionType": "ALL",
            "ageRestrictionMinAge": None,
            "createdAt": "2026-08-31 09:19:26",
            "lastUpdatedAt": "2026-08-31 09:20:01",
        }

    def test_extracts_expected_popup_payload(self) -> None:
        payload = extract_embedded_popup_payload(
            build_html(self.payload),
            expected_source_id="8784",
        )
        self.assertIsNotNone(payload)
        self.assertEqual(8784, payload["id"])

    def test_maps_embedded_fields_without_inference(self) -> None:
        row = parse_detail_html(
            build_html(self.payload),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )

        self.assertEqual("nextjs_embedded_data", row["parse_source"])
        self.assertEqual("STORE", row["event_type_raw"])
        self.assertEqual("서울 성동구 성수이로 62", row["road_address"])
        self.assertEqual("성동구", row["district"])
        self.assertEqual("무신사 메가스토어 성수 1층", row["venue_name"])
        self.assertEqual(["매일 11:00 ~ 22:00"], row["operation_hours_raw"])
        self.assertEqual(1, len(row["benefits_nonempty"]))
        self.assertTrue(row["reservation_info_present"])
        self.assertIsNone(row["reservation_required"])
        self.assertIsNone(row["reservation_url"])
        self.assertEqual(
            "https://cdn.popga.co.kr/main.webp",
            row["main_image_url"],
        )
        self.assertEqual(self.payload, row["source_payload_raw"])

    def test_non_store_event_type_uses_same_structured_payload(self) -> None:
        self.payload["type"] = "EXHIBITION"
        row = parse_detail_html(
            build_html(self.payload),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )
        self.assertEqual("nextjs_embedded_data", row["parse_source"])
        self.assertEqual("EXHIBITION", row["event_type_raw"])
        self.assertEqual("2026-09-29", row["end_date_detail"])

    def test_missing_road_address_uses_valid_seoul_address(self) -> None:
        self.payload["roadAddress"] = None
        self.payload["address"] = "서울특별시 성동구 성수이로 77"
        row = parse_detail_html(
            build_html(self.payload),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )
        self.assertEqual("서울특별시 성동구 성수이로 77", row["road_address"])
        self.assertEqual("성동구", row["district"])
        self.assertIn(
            "road_address_missing_used_address_fallback",
            row["parse_warnings"],
        )

    def test_missing_road_address_does_not_use_non_seoul_address(self) -> None:
        self.payload["roadAddress"] = None
        self.payload["address"] = "부산 해운대구 예시로 1"
        row = parse_detail_html(
            build_html(self.payload),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )
        self.assertIsNone(row["road_address"])
        self.assertIn("road_address_missing", row["parse_warnings"])

    def test_reversed_embedded_dates_are_flagged(self) -> None:
        self.payload["openDate"] = "2026-09-01"
        self.payload["closeDate"] = "2026-02-28"
        row = parse_detail_html(
            build_html(self.payload),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )
        self.assertIn("invalid_date_range", row["parse_warnings"])

    def test_enrichment_uses_list_dates_when_detail_range_is_invalid(self) -> None:
        list_row = {
            "source_id": "8784",
            "name": "목록 이름",
            "category": "기타",
            "start_date": "2026-09-01",
            "end_date": "2027-02-28",
        }
        detail = parse_detail_html(
            build_html({
                **self.payload,
                "openDate": "2026-09-01",
                "closeDate": "2026-02-28",
            }),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )
        row = enrich_with_details([list_row], [detail])[0]
        self.assertEqual("2026-09-01", row["start_date"])
        self.assertEqual("2027-02-28", row["end_date"])

    def test_open_ended_detail_keeps_null_end_date(self) -> None:
        self.payload["closeDate"] = None
        row = parse_detail_html(
            build_html(self.payload),
            "8784",
            "https://www.popga.co.kr/popup/8784",
        )
        self.assertIsNone(row["end_date_detail"])
        self.assertIn(
            "end_date_missing_source_open_ended",
            row["parse_warnings"],
        )

    def test_wrong_expected_id_is_not_accepted(self) -> None:
        payload = extract_embedded_popup_payload(
            build_html(self.payload),
            expected_source_id="9999",
        )
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
