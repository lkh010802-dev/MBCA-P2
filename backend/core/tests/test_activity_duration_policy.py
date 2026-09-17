import unittest

from activity_duration_policy import (
    determine_stay_duration,
    get_activity_duration_policy,
)


class ActivityDurationPolicyTest(unittest.TestCase):
    def test_returns_policy_for_all_supported_activities(self):
        expected = {
            "food": {"min": 50, "default": 60, "max": 70},
            "cafe": {"min": 30, "default": 45, "max": 60},
            "walk": {"min": 30, "default": 45, "max": 60},
            "culture": {"min": 60, "default": 90, "max": 120},
            "entertainment": {"min": 60, "default": 90, "max": 120},
            "shopping": {"min": 45, "default": 60, "max": 75},
            "drink": {"min": 75, "default": 90, "max": 120},
        }

        for activity, policy in expected.items():
            with self.subTest(activity=activity):
                self.assertEqual(get_activity_duration_policy(activity), policy)

    def test_rejects_unsupported_activity(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            get_activity_duration_policy("unknown")

    def test_returned_policy_cannot_mutate_shared_policy(self):
        policy = get_activity_duration_policy("food")
        policy["default"] = 999

        self.assertEqual(get_activity_duration_policy("food")["default"], 60)

    def test_uses_default_when_duration_is_not_specified(self):
        self.assertEqual(determine_stay_duration("cafe"), 45)

    def test_uses_specified_duration_without_min_max_clamping(self):
        self.assertEqual(determine_stay_duration("food", 20), 20)
        self.assertEqual(determine_stay_duration("food", 100), 100)

    def test_rejects_unsupported_activity_when_determining_duration(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            determine_stay_duration("unknown", 60)


if __name__ == "__main__":
    unittest.main()
