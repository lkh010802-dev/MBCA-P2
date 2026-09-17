import unittest

from stay_time_validation import (
    IMPOSSIBLE_BY_STAY_TIME,
    PENDING_TRAVEL_TIME_VALIDATION,
    TIGHT_BY_STAY_TIME,
    validate_selected_places_stay_time,
)


class StayTimeValidationTest(unittest.TestCase):
    def test_explicit_duration_is_used_for_planned_and_minimum(self):
        result = validate_selected_places_stay_time(
            [
                {"activity": "food", "specified_duration_minutes": 20},
                {"activity": "culture", "specified_duration_minutes": 150},
            ],
            available_time_minutes=200,
        )

        self.assertEqual(result["stay_durations_minutes"], [20, 150])
        self.assertEqual(result["minimum_stay_durations_minutes"], [20, 150])
        self.assertEqual(result["status"], PENDING_TRAVEL_TIME_VALIDATION)

    def test_pending_when_default_total_fits_available_time(self):
        result = validate_selected_places_stay_time(
            [{"activity": "food"}, {"activity": "cafe"}],
            available_time_minutes=120,
        )

        self.assertEqual(result["total_stay_duration_minutes"], 105)
        self.assertEqual(result["total_minimum_stay_duration_minutes"], 80)
        self.assertEqual(result["status"], PENDING_TRAVEL_TIME_VALIDATION)

    def test_tight_when_default_total_exceeds_but_minimum_fits(self):
        result = validate_selected_places_stay_time(
            [{"activity": "food"}, {"activity": "cafe"}],
            available_time_minutes=90,
        )

        self.assertEqual(result["total_stay_duration_minutes"], 105)
        self.assertEqual(result["total_minimum_stay_duration_minutes"], 80)
        self.assertEqual(result["status"], TIGHT_BY_STAY_TIME)

    def test_impossible_when_minimum_total_exceeds_available_time(self):
        result = validate_selected_places_stay_time(
            [{"activity": "food"}, {"activity": "cafe"}],
            available_time_minutes=79,
        )

        self.assertEqual(result["status"], IMPOSSIBLE_BY_STAY_TIME)

    def test_mixed_explicit_and_default_durations(self):
        result = validate_selected_places_stay_time(
            [
                {"activity": "food", "specified_duration_minutes": 70},
                {"activity": "cafe"},
            ],
            available_time_minutes=105,
        )

        self.assertEqual(result["stay_durations_minutes"], [70, 45])
        self.assertEqual(result["minimum_stay_durations_minutes"], [70, 30])
        self.assertEqual(result["status"], TIGHT_BY_STAY_TIME)

    def test_pending_when_default_total_equals_available_time(self):
        result = validate_selected_places_stay_time(
            [{"activity": "shopping"}],
            available_time_minutes=60,
        )

        self.assertEqual(result["status"], PENDING_TRAVEL_TIME_VALIDATION)

    def test_existing_single_activity_normal_case(self):
        result = validate_selected_places_stay_time(
            [{"activity": "walk"}],
            available_time_minutes=60,
        )

        self.assertEqual(result["total_stay_duration_minutes"], 45)
        self.assertEqual(result["status"], PENDING_TRAVEL_TIME_VALIDATION)


if __name__ == "__main__":
    unittest.main()
