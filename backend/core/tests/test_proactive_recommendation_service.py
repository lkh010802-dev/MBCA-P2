import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from place_availability import SEOUL_TIMEZONE
from proactive_recommendation_service import find_proactive_suggestion


class ProactiveRecommendationServiceTests(unittest.TestCase):
    def setUp(self):
        self.departure = datetime(2026, 9, 8, 12, 0, tzinfo=SEOUL_TIMEZONE)
        self.start = {"x": 127.0, "y": 37.5}

    def place(self, name="행사", days_left=0, **overrides):
        place = {
            "source": "popup",
            "source_id": name,
            "name": name,
            "latitude": 37.501,
            "longitude": 127.0,
            "category": "culture",
            "start_at": "2026-09-01",
            "end_at": (self.departure.date() + timedelta(days=days_left)).isoformat(),
            "operation_schedule_status": "parsed",
            "operation_schedule": [{}],
        }
        place.update(overrides)
        return place

    @staticmethod
    def open_availability(remaining=120):
        return {
            "status": "open",
            "arrival_at": None,
            "opening_at": None,
            "closing_at": None,
            "remaining_minutes": remaining,
        }

    def find(self, popup_places, **overrides):
        arguments = {
            "start_location": self.start,
            "departure_datetime": self.departure,
            "end_location": None,
            "end_datetime": None,
            "transport_mode": "auto",
            "activities": [],
            "load_popup_places_fn": Mock(return_value=popup_places),
            "load_culture_places_fn": Mock(return_value=[]),
            "get_travel_fn": Mock(return_value={"mode": "walk", "duration_min": 10}),
            "evaluate_availability_fn": Mock(
                return_value=self.open_availability()
            ),
        }
        arguments.update(overrides)
        return find_proactive_suggestion(**arguments)

    def test_today_and_ending_soon_are_recommended(self):
        today = self.find([self.place()])
        soon = self.find([self.place(days_left=3)])

        self.assertEqual(today["reason"], "ending_today")
        self.assertEqual(soon["reason"], "ending_soon")
        self.assertEqual(today["suggestion_type"], "timely")
        self.assertEqual(soon["suggestion_type"], "timely")

    def test_matching_activity_is_timely_today_and_ending_soon(self):
        for days_left in (0, 3):
            with self.subTest(days_left=days_left):
                result = self.find(
                    [self.place(days_left=days_left)],
                    activities=["culture"],
                )
                self.assertEqual(result["suggestion_type"], "timely")

    def test_mismatched_activity_is_detour_only_when_ending_today(self):
        detour = self.find([self.place()], activities=["cafe"])
        excluded = self.find(
            [self.place(days_left=1)],
            activities=["cafe"],
        )

        self.assertEqual(detour["suggestion_type"], "detour")
        self.assertEqual(detour["reason"], "ending_today")
        self.assertIn("다른 선택지로 제안드려요", detour["message"])
        self.assertIsNone(excluded)

    def test_detour_travel_limit_is_inclusive(self):
        allowed = self.find(
            [self.place()],
            activities=["cafe"],
            get_travel_fn=Mock(
                return_value={"mode": "walk", "duration_min": 15}
            ),
        )
        excluded = self.find(
            [self.place()],
            activities=["cafe"],
            get_travel_fn=Mock(
                return_value={"mode": "walk", "duration_min": 16}
            ),
        )

        self.assertIsNotNone(allowed)
        self.assertIsNone(excluded)

    def test_timely_suggestion_is_not_limited_to_fifteen_minutes(self):
        result = self.find(
            [self.place()],
            activities=["culture"],
            get_travel_fn=Mock(
                return_value={"mode": "transit", "duration_min": 30}
            ),
        )

        self.assertEqual(result["suggestion_type"], "timely")

    def test_matching_today_precedes_detour_today(self):
        result = self.find(
            [
                self.place("탈선", category="culture", latitude=37.5001),
                self.place("일치", category="cafe", latitude=37.502),
            ],
            activities=["cafe"],
        )

        self.assertEqual(result["place"]["name"], "일치")
        self.assertEqual(result["suggestion_type"], "timely")

    def test_detour_today_precedes_matching_ending_soon(self):
        result = self.find(
            [
                self.place("일치", days_left=1, category="cafe", latitude=37.5001),
                self.place("탈선", category="culture", latitude=37.502),
            ],
            activities=["cafe"],
        )

        self.assertEqual(result["place"]["name"], "탈선")
        self.assertEqual(result["suggestion_type"], "detour")

    def test_popup_place_includes_card_fields_and_null_urls(self):
        result = self.find([self.place(image_url="https://example.com/image.jpg")])

        self.assertEqual(
            set(result["place"]),
            {
                "source",
                "source_id",
                "name",
                "latitude",
                "longitude",
                "category",
                "start_at",
                "end_at",
                "image_url",
                "detail_url",
                "official_url",
                "operation_schedule",
                "operation_schedule_status",
            },
        )
        self.assertEqual(result["place"]["start_at"], "2026-09-01")
        self.assertEqual(result["place"]["end_at"], "2026-09-08")
        self.assertEqual(
            result["place"]["image_url"],
            "https://example.com/image.jpg",
        )
        self.assertIsNone(result["place"]["detail_url"])
        self.assertIsNone(result["place"]["official_url"])
        self.assertEqual(result["place"]["operation_schedule"], [{}])
        self.assertEqual(
            result["place"]["operation_schedule_status"],
            "parsed",
        )

    def test_seoul_culture_place_uses_same_card_structure(self):
        culture_place = self.place(
            source="seoul_culture",
            detail_url="https://example.com/detail",
            official_url="https://example.com/official",
        )
        result = self.find(
            [],
            load_culture_places_fn=Mock(return_value=[culture_place]),
        )

        self.assertEqual(
            set(result["place"]),
            {
                "source",
                "source_id",
                "name",
                "latitude",
                "longitude",
                "category",
                "start_at",
                "end_at",
                "image_url",
                "detail_url",
                "official_url",
                "operation_schedule",
                "operation_schedule_status",
            },
        )
        self.assertEqual(result["place"]["source"], "seoul_culture")
        self.assertIsNone(result["place"]["image_url"])
        self.assertEqual(
            result["place"]["detail_url"],
            "https://example.com/detail",
        )
        self.assertEqual(result["place"]["operation_schedule"], [{}])
        self.assertEqual(
            result["place"]["operation_schedule_status"],
            "parsed",
        )

    def test_missing_or_distant_end_date_is_excluded(self):
        self.assertIsNone(self.find([self.place(days_left=4)]))
        self.assertIsNone(self.find([self.place(end_at=None)]))

    def test_place_outside_two_kilometers_is_excluded(self):
        self.assertIsNone(self.find([
            self.place(latitude=37.53),
        ]))

    def test_only_open_place_with_enough_minimum_stay_is_recommended(self):
        for status in ("closed", "unknown"):
            with self.subTest(status=status):
                self.assertIsNone(self.find(
                    [self.place()],
                    evaluate_availability_fn=Mock(return_value={
                        **self.open_availability(),
                        "status": status,
                    }),
                ))

        self.assertIsNone(self.find(
            [self.place()],
            evaluate_availability_fn=Mock(
                return_value=self.open_availability(59)
            ),
        ))

    def test_next_schedule_must_leave_minimum_stay_and_buffer(self):
        travel = Mock(side_effect=[
            {"mode": "walk", "duration_min": 10},
            {"mode": "walk", "duration_min": 30},
        ])
        result = self.find(
            [self.place()],
            end_location={"x": 127.1, "y": 37.6},
            end_datetime=self.departure + timedelta(minutes=100),
            get_travel_fn=travel,
        )

        self.assertIsNone(result)

    def test_end_time_without_location_limits_visitable_minutes(self):
        travel = Mock(return_value={"mode": "walk", "duration_min": 1})
        result = self.find(
            [self.place()],
            end_datetime=self.departure + timedelta(minutes=120),
            get_travel_fn=travel,
            evaluate_availability_fn=Mock(
                return_value=self.open_availability(396)
            ),
        )

        self.assertEqual(result["visitable_minutes"], 109)
        self.assertIsNone(result["fits_before_next_schedule"])
        self.assertEqual(travel.call_count, 1)

    def test_visitable_minutes_uses_earlier_operation_or_user_limit(self):
        for remaining, expected in ((396, 109), (70, 70)):
            with self.subTest(remaining=remaining):
                result = self.find(
                    [self.place()],
                    end_datetime=self.departure + timedelta(minutes=120),
                    get_travel_fn=Mock(
                        return_value={"mode": "walk", "duration_min": 1}
                    ),
                    evaluate_availability_fn=Mock(
                        return_value=self.open_availability(remaining)
                    ),
                )

                self.assertEqual(result["visitable_minutes"], expected)

    def test_user_time_limit_excludes_place_below_minimum_stay(self):
        for activities in ([], ["cafe"]):
            with self.subTest(activities=activities):
                self.assertIsNone(self.find(
                    [self.place()],
                    activities=activities,
                    end_datetime=self.departure + timedelta(minutes=60),
                    get_travel_fn=Mock(
                        return_value={"mode": "walk", "duration_min": 10}
                    ),
                ))

        self.assertIsNone(self.find(
            [self.place()],
            end_datetime=self.departure + timedelta(minutes=10),
            get_travel_fn=Mock(
                return_value={"mode": "walk", "duration_min": 10}
            ),
        ))

    def test_next_schedule_keeps_two_travels_and_buffer(self):
        travel = Mock(side_effect=[
            {"mode": "walk", "duration_min": 10},
            {"mode": "walk", "duration_min": 20},
        ])
        result = self.find(
            [self.place()],
            end_location={"x": 127.1, "y": 37.6},
            end_datetime=self.departure + timedelta(minutes=120),
            get_travel_fn=travel,
        )

        self.assertEqual(result["visitable_minutes"], 80)
        self.assertTrue(result["fits_before_next_schedule"])
        self.assertEqual(travel.call_count, 2)

    def test_no_next_schedule_does_not_require_onward_travel(self):
        travel = Mock(return_value={"mode": "walk", "duration_min": 10})
        result = self.find([self.place()], get_travel_fn=travel)

        self.assertIsNotNone(result)
        self.assertIsNone(result["fits_before_next_schedule"])
        self.assertEqual(travel.call_count, 1)

    def test_failed_candidate_continues_to_next_candidate(self):
        travel = Mock(side_effect=[None, {"mode": "walk", "duration_min": 10}])
        result = self.find(
            [self.place("첫째"), self.place("둘째", latitude=37.502)],
            get_travel_fn=travel,
        )

        self.assertEqual(result["place"]["name"], "둘째")

    def test_each_source_failure_isolated(self):
        culture = Mock(return_value=[self.place("문화행사")])
        result = self.find(
            [],
            load_popup_places_fn=Mock(side_effect=RuntimeError),
            load_culture_places_fn=culture,
        )
        self.assertEqual(result["place"]["name"], "문화행사")

        result = self.find(
            [self.place("팝업")],
            load_culture_places_fn=Mock(side_effect=RuntimeError),
        )
        self.assertEqual(result["place"]["name"], "팝업")

    def test_no_candidate_returns_none(self):
        self.assertIsNone(self.find([]))

    def test_candidate_category_is_not_filtered_by_requested_activity(self):
        result = self.find([self.place(category="entertainment")])
        self.assertEqual(result["place"]["category"], "entertainment")

    def test_only_three_candidates_use_actual_travel(self):
        travel = Mock(return_value={"mode": "walk", "duration_min": 10})
        result = self.find(
            [self.place(str(index), latitude=37.5 + index / 10000) for index in range(1, 5)],
            get_travel_fn=travel,
            evaluate_availability_fn=Mock(return_value={
                **self.open_availability(),
                "status": "closed",
            }),
        )

        self.assertIsNone(result)
        self.assertEqual(travel.call_count, 3)

    def test_future_departure_message_does_not_say_now(self):
        future = datetime.now(SEOUL_TIMEZONE) + timedelta(hours=2)
        result = self.find(
            [self.place(
                start_at=future.date().isoformat(),
                end_at=future.date().isoformat(),
            )],
            departure_datetime=future,
        )

        self.assertNotIn("지금 출발하면", result["message"])

    def test_message_templates_and_travel_modes(self):
        current_cases = [
            (0, "walk", "오늘이 마지막 날이에요", "도보로", "지금 출발하면"),
            (2, "transit", "2일 뒤 종료돼요", "대중교통으로", "지금 방문하면"),
        ]

        for days_left, mode, ending, mode_text, timing in current_cases:
            with self.subTest(days_left=days_left, mode=mode):
                result = self.find(
                    [self.place(days_left=days_left)],
                    get_travel_fn=Mock(
                        return_value={"mode": mode, "duration_min": 10}
                    ),
                )
                message = result["message"]
                self.assertIn("'행사',", message)
                self.assertIn(ending, message)
                self.assertIn(mode_text, message)
                self.assertIn(timing, message)
                self.assertIn("약 120분 둘러볼 수 있어요", message)
                self.assertNotIn("이(가)", message)

        future = datetime.now(SEOUL_TIMEZONE) + timedelta(hours=2)
        for days_left, mode, mode_text in (
            (0, "car", "차량으로"),
            (2, "unknown", "약 10분"),
        ):
            with self.subTest(future=True, days_left=days_left, mode=mode):
                result = self.find(
                    [self.place(
                        days_left=days_left,
                        start_at=future.date().isoformat(),
                        end_at=(future.date() + timedelta(days=days_left)).isoformat(),
                    )],
                    departure_datetime=future,
                    get_travel_fn=Mock(
                        return_value={"mode": mode, "duration_min": 10}
                    ),
                )
                message = result["message"]
                self.assertIn(mode_text, message)
                self.assertIn("도착 후 약 120분 둘러볼 수 있어요", message)
                self.assertNotIn("지금", message)
                self.assertNotIn("현재", message)
                self.assertNotIn("이(가)", message)


if __name__ == "__main__":
    unittest.main()
