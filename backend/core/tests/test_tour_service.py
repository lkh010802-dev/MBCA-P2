import unittest
from datetime import date
from unittest.mock import Mock, call, patch

from tour_service import get_hub_places, get_latest_hub_places


class TourServiceTest(unittest.TestCase):

    @patch("tour_service.requests.get")
    def test_empty_string_items_returns_empty_list(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "response": {
                "header": {"resultCode": "0000"},
                "body": {"items": "", "totalCount": 0},
            }
        }
        mock_get.return_value = response

        self.assertEqual(get_hub_places("11440", "202609"), [])

    @patch("tour_service.get_hub_places")
    def test_finds_latest_available_month_without_repeating_calls(
        self,
        mock_get_hub_places,
    ):
        places = [{"hubTatsNm": "최신 관광지"}]
        mock_get_hub_places.side_effect = [[], [], places]

        result = get_latest_hub_places(
            "11440",
            reference_date=date(2026, 9, 7),
        )

        self.assertEqual(result, places)
        self.assertEqual(
            mock_get_hub_places.call_args_list,
            [
                call(gu_code="11440", base_ym="202609"),
                call(gu_code="11440", base_ym="202608"),
                call(gu_code="11440", base_ym="202607"),
            ],
        )

    @patch("tour_service.get_hub_places", return_value=[])
    def test_returns_empty_after_bounded_lookback(self, mock_get_hub_places):
        result = get_latest_hub_places(
            "11440",
            reference_date=date(2026, 2, 1),
            lookback_months=3,
        )

        self.assertEqual(result, [])
        self.assertEqual(
            mock_get_hub_places.call_args_list,
            [
                call(gu_code="11440", base_ym="202602"),
                call(gu_code="11440", base_ym="202601"),
                call(gu_code="11440", base_ym="202512"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
