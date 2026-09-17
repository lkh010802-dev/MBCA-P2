import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

import congestion_service


class CongestionApiTests(unittest.TestCase):

    @patch("congestion_service.requests.get")
    def test_congestion_response_is_returned(self, mock_get):
        response = Mock()
        response.json.return_value = {
            "SeoulRtd.citydata_ppltn": [
                {
                    "FCST_PPLTN": [],
                }
            ]
        }
        mock_get.return_value = response

        result = congestion_service.get_congestion_data("POI001")

        self.assertIn("SeoulRtd.citydata_ppltn", result)
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 10)

    @patch(
        "congestion_service.requests.get",
        side_effect=requests.Timeout,
    )
    def test_congestion_timeout_returns_none(self, mock_get):
        result = congestion_service.get_congestion_data("POI001")

        self.assertIsNone(result)
        mock_get.assert_called_once()

    def test_nearest_forecast_is_selected(self):
        congestion_data = {
            "SeoulRtd.citydata_ppltn": [
                {
                    "FCST_PPLTN": [
                        {
                            "FCST_TIME": "2026-09-02 18:00",
                            "FCST_CONGEST_LVL": "보통",
                        },
                        {
                            "FCST_TIME": "2026-09-02 19:00",
                            "FCST_CONGEST_LVL": "붐빔",
                        },
                    ]
                }
            ]
        }
        arrival_datetime = datetime(
            2026,
            9,
            2,
            18,
            10,
            tzinfo=ZoneInfo("Asia/Seoul"),
        )

        result = congestion_service.get_nearest_forecast_congestion(
            congestion_data,
            arrival_datetime,
        )

        self.assertEqual(result["FCST_TIME"], "2026-09-02 18:00")

    def test_missing_forecast_returns_none(self):
        result = congestion_service.get_nearest_forecast_congestion(
            {},
            datetime.now(tz=ZoneInfo("Asia/Seoul")),
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
