import unittest
from datetime import datetime
from threading import Event
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from main import app


def intent(**overrides):
    result = {
        "start_location_text": None,
        "target_location_text": None,
        "target_location_scope": None,
        "end_location_text": None,
        "start_time": "12:00",
        "end_time": None,
        "activities": ["cafe"],
        "transport_mode": "auto",
    }
    result.update(overrides)
    return result


def candidate(code, name, latitude, longitude):
    return {
        "AREA_CD": code,
        "AREA_NM": name,
        "CATEGORY": "발달상권",
        "latitude": latitude,
        "longitude": longitude,
    }


def activity_scores(candidates):
    return pd.DataFrame([
        {
            **place,
            "food_score": 1,
            "cafe_score": index,
            "drink_score": 1,
            "entertainment_score": 1,
            "walk_score": 1,
            "culture_score": 1,
            "shopping_score": 1,
        }
        for index, place in enumerate(candidates, start=3)
    ])


class RecommendAPITests(unittest.TestCase):
    def setUp(self):
        self.local_resd_patcher = patch(
            "main.load_local_resd_candidates",
            return_value=pd.DataFrame(),
        )
        self.local_resd_patcher.start()
        self.addCleanup(self.local_resd_patcher.stop)
        self.proactive_patcher = patch(
            "main.find_proactive_suggestion",
            return_value=None,
        )
        self.mock_proactive = self.proactive_patcher.start()
        self.addCleanup(self.proactive_patcher.stop)
        self.client = TestClient(app)
        self.candidates = [
            candidate("A", "지역 A", 37.50, 127.00),
            candidate("B", "지역 B", 37.51, 127.01),
            candidate("C", "지역 C", 37.52, 127.02),
        ]

    def test_proactive_suggestion_is_added_without_replacing_region_result(self):
        suggestion = {"reason": "ending_today", "place": {"name": "팝업"}}
        self.mock_proactive.return_value = suggestion

        with (
            patch("main.parse_user_intent", return_value=intent()),
            patch("main.load_poi_candidates", return_value=self.candidates),
            patch(
                "main.load_poi_activity_scores",
                return_value=activity_scores(self.candidates),
            ),
            patch("main.get_travel", return_value={"duration_min": 20}),
            patch("main.get_congestion_data", return_value=None),
            patch("main.generate_recommendation_message", return_value="추천 설명"),
        ):
            response = self.client.post(
                "/recommend",
                json={
                    "user_message": "근처 카페 추천해줘",
                    "gps_latitude": 37.4765,
                    "gps_longitude": 126.9816,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proactive_suggestion"], suggestion)
        self.assertEqual(len(response.json()["other_areas"]), 3)
        self.assertEqual(
            self.mock_proactive.call_args.kwargs["activities"],
            ["cafe"],
        )

    @patch("main.generate_recommendation_message", return_value="추천 설명")
    @patch("main.get_congestion_data", return_value=None)
    @patch("main.get_travel", return_value={"duration_min": 20})
    @patch("main.load_poi_activity_scores")
    @patch("main.load_poi_candidates")
    @patch("main.parse_user_intent")
    def test_gps_normal_flow_preserves_response_contract(
        self,
        mock_parse,
        mock_load_candidates,
        mock_load_scores,
        mock_get_travel,
        mock_get_congestion,
        mock_generate_message,
    ):
        mock_parse.return_value = intent()
        mock_load_candidates.return_value = self.candidates
        mock_load_scores.return_value = activity_scores(self.candidates)

        response = self.client.post(
            "/recommend",
            json={
                "user_message": "근처 카페 추천해줘",
                "gps_latitude": 37.4765,
                "gps_longitude": 126.9816,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "recommendation_message",
                "proactive_suggestion",
                "recommendation_context",
                "target_area",
                "current_area",
                "other_areas",
                "extended_areas",
            },
        )
        self.assertEqual(body["recommendation_message"], "추천 설명")
        self.assertIsNone(body["proactive_suggestion"])
        self.assertEqual(
            body["recommendation_context"],
            {
                "activities": ["cafe"],
                "activity_preferences": {},
                "transport_mode": "auto",
                "space_preference": None,
                "start_location": {
                    "latitude": 37.4765,
                    "longitude": 126.9816,
                },
                "departure_datetime": body["recommendation_context"][
                    "departure_datetime"
                ],
                "end_location": None,
                "end_datetime": None,
                "available_time_minutes": None,
            },
        )
        departure = datetime.fromisoformat(
            body["recommendation_context"]["departure_datetime"]
        )
        self.assertIsNotNone(departure.utcoffset())
        self.assertEqual(departure.strftime("%H:%M"), "12:00")
        self.assertNotIn("companions", body["recommendation_context"])
        self.assertNotIn("budget_max", body["recommendation_context"])
        self.assertNotIn("budget_preference", body["recommendation_context"])
        self.assertIsNone(body["target_area"])
        self.assertIsNone(body["current_area"])
        self.assertEqual(len(body["other_areas"]), 3)
        self.assertEqual(body["extended_areas"], [])
        mock_get_travel.assert_called()
        mock_generate_message.assert_called_once()

    @patch("region_recommendation_service.get_nearest_forecast_congestion")
    @patch("region_recommendation_service.datetime")
    @patch("main.generate_recommendation_message", return_value="추천 설명")
    @patch("main.get_congestion_data", return_value={"forecast": True})
    @patch("main.get_travel", return_value={"duration_min": 20})
    @patch("main.load_poi_activity_scores")
    @patch("main.load_poi_candidates")
    @patch("main.parse_user_intent")
    def test_start_time_period_drives_arrival_and_congestion_time(
        self,
        mock_parse,
        mock_load_candidates,
        mock_load_scores,
        mock_get_travel,
        mock_get_congestion,
        mock_generate_message,
        mock_datetime,
        mock_nearest_forecast,
    ):
        now = datetime.fromisoformat("2026-09-14T11:00:00+09:00")
        mock_datetime.now.return_value = now
        mock_parse.return_value = intent(
            start_time=None,
            start_time_period="evening",
        )
        mock_load_candidates.return_value = self.candidates
        mock_load_scores.return_value = activity_scores(self.candidates)
        mock_nearest_forecast.return_value = {
            "FCST_CONGEST_LVL": "보통",
        }

        response = self.client.post(
            "/recommend",
            json={
                "user_message": "이따 밤에 분위기 좋은 카페 있어?",
                "gps_latitude": 37.4765,
                "gps_longitude": 126.9816,
            },
        )

        self.assertEqual(response.status_code, 200)
        context = response.json()["recommendation_context"]
        self.assertEqual(
            datetime.fromisoformat(context["departure_datetime"]),
            datetime.fromisoformat("2026-09-14T18:00:00+09:00"),
        )
        self.assertIsNone(context["available_time_minutes"])
        self.assertTrue(mock_nearest_forecast.called)
        for call in mock_nearest_forecast.call_args_list:
            self.assertEqual(
                call.args[1],
                datetime.fromisoformat("2026-09-14T18:20:00+09:00"),
            )

    @patch("main.generate_recommendation_message", return_value="목적지 추천")
    @patch("main.get_congestion_data", return_value=None)
    @patch("main.get_travel", return_value={"duration_min": 20})
    @patch("main.search_location")
    @patch("main.load_poi_activity_scores")
    @patch("main.load_poi_candidates")
    @patch("main.parse_user_intent")
    def test_text_target_place_and_end_location_return_target_area_only(
        self,
        mock_parse,
        mock_load_candidates,
        mock_load_scores,
        mock_search_location,
        mock_get_travel,
        mock_get_congestion,
        mock_generate_message,
    ):
        mock_parse.return_value = intent(
            start_location_text="서울역",
            target_location_text="강남역",
            target_location_scope="place",
            end_location_text="잠실역",
            end_time="15:00",
            transport_mode="public_transit",
            space_preference="indoor",
        )
        mock_load_candidates.return_value = self.candidates
        mock_load_scores.return_value = activity_scores(self.candidates)
        mock_search_location.side_effect = [
            {"name": "서울역", "x": 126.97, "y": 37.55},
            {"name": "강남역", "x": 127.01, "y": 37.51},
            {"name": "잠실역", "x": 127.10, "y": 37.51},
        ]

        response = self.client.post(
            "/recommend",
            json={"user_message": "서울역에서 강남역에 들렀다가 잠실로 가"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["target_area"]["AREA_CD"], "B")
        self.assertEqual(
            body["recommendation_context"],
            {
                "activities": ["cafe"],
                "activity_preferences": {},
                "transport_mode": "public_transit",
                "space_preference": "indoor",
                "start_location": {
                    "latitude": 37.55,
                    "longitude": 126.97,
                },
                "departure_datetime": body["recommendation_context"][
                    "departure_datetime"
                ],
                "end_location": {
                    "latitude": 37.51,
                    "longitude": 127.10,
                },
                "end_datetime": body["recommendation_context"][
                    "end_datetime"
                ],
                "available_time_minutes": 180,
            },
        )
        departure = datetime.fromisoformat(
            body["recommendation_context"]["departure_datetime"]
        )
        end = datetime.fromisoformat(
            body["recommendation_context"]["end_datetime"]
        )
        self.assertIsNotNone(departure.utcoffset())
        self.assertIsNotNone(end.utcoffset())
        self.assertEqual(departure.strftime("%H:%M"), "12:00")
        self.assertEqual(end.strftime("%H:%M"), "15:00")
        self.assertIsNone(body["current_area"])
        self.assertEqual(body["other_areas"], [])
        self.assertEqual(mock_search_location.call_count, 3)
        self.assertTrue(all(
            call.kwargs["transport_mode"] == "public_transit"
            for call in mock_get_travel.call_args_list
        ))

    @patch("main.generate_recommendation_message", return_value="추천 설명")
    @patch("main.get_congestion_data", return_value=None)
    @patch("main.get_travel", return_value={"duration_min": 20})
    @patch("main.load_poi_activity_scores")
    @patch("main.load_poi_candidates")
    @patch("main.parse_user_intent")
    def test_empty_activities_are_preserved_in_recommendation_context(
        self,
        mock_parse,
        mock_load_candidates,
        mock_load_scores,
        mock_get_travel,
        mock_get_congestion,
        mock_generate_message,
    ):
        mock_parse.return_value = intent(activities=[])
        mock_load_candidates.return_value = self.candidates
        mock_load_scores.return_value = activity_scores(self.candidates)

        response = self.client.post(
            "/recommend",
            json={
                "user_message": "근처 추천해줘",
                "gps_latitude": 37.4765,
                "gps_longitude": 126.9816,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["recommendation_context"],
            {
                "activities": [],
                "activity_preferences": {},
                "transport_mode": "auto",
                "space_preference": None,
                "start_location": {
                    "latitude": 37.4765,
                    "longitude": 126.9816,
                },
                "departure_datetime": response.json()[
                    "recommendation_context"
                ]["departure_datetime"],
                "end_location": None,
                "end_datetime": None,
                "available_time_minutes": None,
            },
        )

    @patch("main.generate_recommendation_message", return_value="일부 후보 추천")
    @patch("main.get_congestion_data", return_value=None)
    @patch("main.load_poi_activity_scores")
    @patch("main.load_poi_candidates")
    @patch("main.parse_user_intent")
    def test_failed_travel_candidate_is_skipped_without_losing_valid_candidates(
        self,
        mock_parse,
        mock_load_candidates,
        mock_load_scores,
        mock_get_congestion,
        mock_generate_message,
    ):
        candidates = self.candidates[:2]
        mock_parse.return_value = intent()
        mock_load_candidates.return_value = candidates
        mock_load_scores.return_value = activity_scores(candidates)

        def travel(_, __, end_x, ___, transport_mode="auto"):
            return None if end_x == 127.00 else {"duration_min": 20}

        with patch("main.get_travel", side_effect=travel):
            response = self.client.post(
                "/recommend",
                json={
                    "user_message": "근처 카페 추천해줘",
                    "gps_latitude": 37.4765,
                    "gps_longitude": 126.9816,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [place["AREA_CD"] for place in body["other_areas"]],
            ["B"],
        )
        self.assertEqual(body["other_areas"][0]["congestion_score"], 3)

    @patch("main.generate_recommendation_message")
    @patch("main.load_poi_candidates", return_value=[])
    @patch("main.parse_user_intent", return_value=intent())
    def test_missing_start_location_preserves_error_contract(
        self,
        mock_parse,
        mock_load_candidates,
        mock_generate_message,
    ):
        response = self.client.post(
            "/recommend",
            json={"user_message": "카페 추천해줘"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "error": "start_location_missing",
                "message": "시작 위치 정보가 필요합니다.",
            },
        )
        mock_generate_message.assert_not_called()

    def test_performance_metrics_do_not_change_result_or_api_calls(self):
        expected_candidates = self.candidates
        expected_scores = activity_scores(expected_candidates)

        def proactive(**kwargs):
            travel = kwargs["get_travel_fn"]
            travel(127.0, 37.5, 127.01, 37.51, transport_mode="auto")
            travel(127.0, 37.5, 127.02, 37.52, transport_mode="auto")
            return None

        self.mock_proactive.side_effect = proactive

        with (
            patch("main.parse_user_intent", return_value=intent()),
            patch("main.load_poi_candidates", return_value=expected_candidates),
            patch("main.load_poi_activity_scores", return_value=expected_scores),
            patch(
                "main.get_travel",
                return_value={"mode": "transit", "duration_min": 20},
            ) as mock_get_travel,
            patch("main.get_congestion_data", return_value=None) as mock_congestion,
            patch(
                "main.generate_recommendation_message",
                return_value="추천 설명",
            ),
            self.assertLogs("uvicorn.error", level="INFO") as captured_logs,
        ):
            response = self.client.post(
                "/recommend",
                json={
                    "user_message": "근처 카페 추천해줘",
                    "gps_latitude": 37.4765,
                    "gps_longitude": 126.9816,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendation_message"], "추천 설명")
        self.assertEqual(
            [place["AREA_CD"] for place in response.json()["other_areas"]],
            ["C", "B", "A"],
        )
        self.assertNotIn("performance", response.json())
        self.assertEqual(mock_get_travel.call_count, 5)
        self.assertEqual(mock_congestion.call_count, 3)

        performance_log = "\n".join(captured_logs.output)
        self.assertIn("[PERFORMANCE]", performance_log)
        self.assertIn("proactive_travel=", performance_log)
        self.assertIn("proactive_travel=0.", performance_log)
        self.assertIn("region_travel=", performance_log)
        self.assertIn("congestion=", performance_log)
        self.assertRegex(
            performance_log,
            r"region_travel=\d+\.\d+s calls=3",
        )
        self.assertIn("calls=2", performance_log)
        self.assertIn("calls=3", performance_log)

    def test_parallel_travel_completion_order_does_not_change_candidate_order(self):
        candidates = [
            candidate(
                chr(ord("A") + index),
                f"지역 {chr(ord('A') + index)}",
                37.50 + index * 0.01,
                127.00 + index * 0.01,
            )
            for index in range(5)
        ]
        scores = activity_scores(candidates)
        scores["cafe_score"] = 5
        c_completed = Event()
        b_completed = Event()

        def travel_pair(place, **_):
            if place["AREA_CD"] == "A":
                self.assertTrue(b_completed.wait(timeout=1))
            elif place["AREA_CD"] == "B":
                self.assertTrue(c_completed.wait(timeout=1))
                b_completed.set()
            elif place["AREA_CD"] == "C":
                c_completed.set()
            return ({"duration_min": 20}, {"duration_min": 0})

        with (
            patch("main.parse_user_intent", return_value=intent()),
            patch("main.load_poi_candidates", return_value=candidates),
            patch("main.load_poi_activity_scores", return_value=scores),
            patch("main.get_congestion_data", return_value=None),
            patch(
                "region_recommendation_service._get_candidate_travel_pair",
                side_effect=travel_pair,
            ),
        ):
            response = self.client.post(
                "/recommend",
                json={
                    "user_message": "근처 카페 추천해줘",
                    "gps_latitude": 37.40,
                    "gps_longitude": 126.90,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [place["AREA_CD"] for place in response.json()["other_areas"]],
            ["A", "B", "C"],
        )


if __name__ == "__main__":
    unittest.main()
