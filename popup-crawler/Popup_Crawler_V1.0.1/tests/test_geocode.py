from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from integration.geocode import enrich_missing_coordinates, valid_coordinate


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, *, address_payloads=None, keyword_payloads=None) -> None:
        self.address_payloads = address_payloads or {}
        self.keyword_payloads = keyword_payloads or {}
        self.calls = []

    def get(self, url, *, headers, params, timeout):
        query = params["query"]
        self.calls.append((url, query))
        if "address.json" in url:
            return FakeResponse(self.address_payloads.get(query, {"documents": []}))
        return FakeResponse(self.keyword_payloads.get(query, {"documents": []}))


class GeocodeTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "popup_id": "preview_1",
            "name": "테스트 팝업",
            "venue_name": None,
            "address": "서울 송파구 올림픽로 300 롯데월드몰",
            "address_base": "서울 송파구 올림픽로 300",
            "district": "송파구",
            "latitude": None,
            "longitude": None,
        }
        row.update(overrides)
        return row

    def test_valid_coordinate_accepts_seoul_only(self):
        self.assertTrue(valid_coordinate(37.513, 127.104))
        self.assertFalse(valid_coordinate(35.1796, 129.0756))
        self.assertFalse(valid_coordinate(None, None))

    def test_existing_valid_coordinate_is_never_overwritten(self):
        row = self._row(latitude=37.51, longitude=127.10)
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [row], api_key="test", cache_path=Path(tmp) / "cache.json",
                session=FakeSession(),
            )
        self.assertEqual(37.51, enriched[0]["latitude"])
        self.assertEqual(127.10, enriched[0]["longitude"])
        self.assertEqual("source", enriched[0]["coordinate_source"])
        self.assertEqual(0, report["filled_total"])
        self.assertEqual([], unresolved)

    def test_same_address_reference_reuse_needs_no_api_key(self):
        row = self._row()
        reference = self._row(latitude=37.513751, longitude=127.104446)
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [row], api_key="", cache_path=Path(tmp) / "cache.json",
                reference_rows=[reference],
            )
        self.assertAlmostEqual(37.513751, enriched[0]["latitude"])
        self.assertAlmostEqual(127.104446, enriched[0]["longitude"])
        self.assertEqual("same_address_reuse", enriched[0]["coordinate_source"])
        self.assertEqual(1, report["same_address_reused"])
        self.assertEqual(0, report["api_calls"])
        self.assertEqual([], unresolved)

    def test_kakao_address_search_fills_and_caches(self):
        query = "서울 송파구 올림픽로 300"
        session = FakeSession(address_payloads={
            query: {
                "documents": [{
                    "address_name": "서울 송파구 신천동 29",
                    "x": "127.104446890835",
                    "y": "37.5137519612953",
                    "road_address": {
                        "address_name": query,
                        "region_1depth_name": "서울",
                        "region_2depth_name": "송파구",
                    },
                }]
            }
        })
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            first, report1, unresolved1 = enrich_missing_coordinates(
                [self._row()], api_key="test", cache_path=cache, session=session,
            )
            second_session = FakeSession()
            second, report2, unresolved2 = enrich_missing_coordinates(
                [self._row()], api_key="test", cache_path=cache, session=second_session,
            )
        self.assertEqual("kakao_address", first[0]["coordinate_source"])
        self.assertEqual(1, report1["kakao_address_filled"])
        self.assertEqual([], unresolved1)
        self.assertEqual("kakao_address_cache", second[0]["coordinate_source"])
        self.assertEqual(1, report2["cache_hits"])
        self.assertEqual(0, report2["api_calls"])
        self.assertEqual([], unresolved2)

    def test_keyword_fallback_requires_supporting_location_evidence(self):
        row = self._row(
            address="서울 용산 아이파크몰 3F 도파민스테이션",
            address_base=None,
            district=None,
            venue_name="용산 아이파크몰",
        )
        query = "용산 아이파크몰 서울"
        session = FakeSession(keyword_payloads={
            query: {
                "documents": [{
                    "place_name": "아이파크몰 용산점",
                    "road_address_name": "서울 용산구 한강대로23길 55",
                    "address_name": "서울 용산구 한강로3가 40-999",
                    "x": "126.964741503485",
                    "y": "37.5297718014452",
                    "id": "12345",
                }]
            }
        })
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [row], api_key="test", cache_path=Path(tmp) / "cache.json", session=session,
            )
        self.assertEqual("kakao_keyword", enriched[0]["coordinate_source"])
        self.assertEqual("12345", enriched[0]["coordinate_kakao_place_id"])
        self.assertEqual(1, report["kakao_keyword_filled"])
        self.assertEqual([], unresolved)

    def test_spaced_numbered_gil_is_repaired_before_address_search(self):
        corrected = "서울 송파구 백제고분로41길 24"
        row = self._row(
            address="서울 송파구 백제고분로 41길 24 2층, 하우피 송리단길",
            address_base="서울 송파구 백제고분로 41",
            district="송파구",
        )
        session = FakeSession(address_payloads={
            corrected: {
                "documents": [{
                    "address_name": "서울 송파구 송파동 25",
                    "x": "127.1085",
                    "y": "37.5058",
                    "road_address": {
                        "address_name": corrected,
                        "region_1depth_name": "서울",
                        "region_2depth_name": "송파구",
                    },
                }]
            }
        })
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [row], api_key="test", cache_path=Path(tmp) / "cache.json", session=session,
            )
        self.assertEqual(corrected, enriched[0]["address_base"])
        self.assertEqual("kakao_address", enriched[0]["coordinate_source"])
        self.assertEqual([], unresolved)
        self.assertIn(("https://dapi.kakao.com/v2/local/search/address.json", corrected), session.calls)

    def test_freeform_mall_address_uses_simplified_place_hint(self):
        row = self._row(
            address="서울 용산 아이파크몰 3F 도파민스테이션",
            address_base=None,
            district=None,
            venue_name=None,
            name="마법 세계가 용산에 떴다?",
        )
        query = "용산 아이파크몰 서울"
        session = FakeSession(keyword_payloads={
            query: {
                "documents": [{
                    "place_name": "아이파크몰 용산점",
                    "road_address_name": "서울 용산구 한강대로23길 55",
                    "address_name": "서울 용산구 한강로3가 40-999",
                    "x": "126.964741503485",
                    "y": "37.5297718014452",
                    "id": "12345",
                }]
            }
        })
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [row], api_key="test", cache_path=Path(tmp) / "cache.json", session=session,
            )
        self.assertEqual("용산구", enriched[0]["district"])
        self.assertEqual("kakao_keyword", enriched[0]["coordinate_source"])
        self.assertEqual(query, enriched[0]["coordinate_query"])
        self.assertEqual([], unresolved)

    def test_hashtag_address_extracts_venue_hint(self):
        row = self._row(
            address="서울 #시든꽃에눈물을 #태하의방 #용산팝업 #용산아이파크몰",
            address_base=None,
            district=None,
            venue_name=None,
            name="태하의 방에 직접 들어가 볼 수 있다고? 🌹",
        )
        query = "용산아이파크몰 서울"
        session = FakeSession(keyword_payloads={
            query: {
                "documents": [{
                    "place_name": "아이파크몰 용산점",
                    "road_address_name": "서울 용산구 한강대로23길 55",
                    "address_name": "서울 용산구 한강로3가 40-999",
                    "x": "126.964741503485",
                    "y": "37.5297718014452",
                    "id": "12345",
                }]
            }
        })
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [row], api_key="test", cache_path=Path(tmp) / "cache.json", session=session,
            )
        self.assertEqual("용산구", enriched[0]["district"])
        self.assertEqual("kakao_keyword", enriched[0]["coordinate_source"])
        self.assertEqual(query, enriched[0]["coordinate_query"])
        self.assertEqual([], unresolved)

    def test_outside_seoul_result_is_rejected(self):
        query = "서울 송파구 올림픽로 300"
        session = FakeSession(address_payloads={
            query: {
                "documents": [{
                    "address_name": "부산 중구 중앙대로 1",
                    "x": "129.0756",
                    "y": "35.1796",
                }]
            }
        })
        with tempfile.TemporaryDirectory() as tmp:
            enriched, report, unresolved = enrich_missing_coordinates(
                [self._row()], api_key="test", cache_path=Path(tmp) / "cache.json", session=session,
            )
        self.assertIsNone(enriched[0]["latitude"])
        self.assertGreaterEqual(len(unresolved), 1)
        self.assertEqual(0, report["filled_total"])


if __name__ == "__main__":
    unittest.main()
