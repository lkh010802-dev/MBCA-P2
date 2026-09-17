import unittest

from route_leg_builder import build_travel_legs


class RouteLegBuilderTest(unittest.TestCase):
    def test_builds_legs_in_selected_place_order_with_end_location(self):
        start = {"latitude": 37.1, "longitude": 127.1}
        place_a = {"name": "A", "latitude": 37.2, "longitude": 127.2}
        place_b = {"name": "B", "latitude": 37.3, "longitude": 127.3}
        end = {"latitude": 37.4, "longitude": 127.4}

        result = build_travel_legs(start, [place_a, place_b], end)

        self.assertEqual(
            result,
            [
                {
                    "origin": start,
                    "destination": {
                        "latitude": 37.2,
                        "longitude": 127.2,
                    },
                },
                {
                    "origin": {
                        "latitude": 37.2,
                        "longitude": 127.2,
                    },
                    "destination": {
                        "latitude": 37.3,
                        "longitude": 127.3,
                    },
                },
                {
                    "origin": {
                        "latitude": 37.3,
                        "longitude": 127.3,
                    },
                    "destination": end,
                },
            ],
        )

    def test_ends_at_last_place_when_end_location_is_missing(self):
        result = build_travel_legs(
            {"latitude": 37.1, "longitude": 127.1},
            [
                {"latitude": 37.2, "longitude": 127.2},
                {"latitude": 37.3, "longitude": 127.3},
            ],
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(
            result[-1]["destination"],
            {"latitude": 37.3, "longitude": 127.3},
        )

    def test_builds_one_leg_for_single_selected_place(self):
        result = build_travel_legs(
            {"latitude": 37.1, "longitude": 127.1},
            [{"latitude": 37.2, "longitude": 127.2}],
        )

        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
