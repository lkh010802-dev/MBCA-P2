import unittest
from pathlib import Path
from unittest.mock import patch

from llm_service import (
    FREEZE_DIR,
    generate_recommendation_message,
    parse_user_intent,
)
from models import StructuredConditions


class LlmServiceTest(unittest.TestCase):
    def test_prompt_requires_explicit_current_location_as_start(self):
        prompt = Path(
            FREEZE_DIR / "intent_parser_prompt_team_v1_3_COST_OPT.txt"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '"지금 대림인데 8시까지 신림 가기 전에 어디 들를 데가 있을까?" '
            '→ start="대림", target=null, end="신림".',
            prompt,
        )
        self.assertIn(
            "사용자가 출발 위치를 명시하지 않았을 때만 백엔드가 GPS를 fallback으로 사용한다",
            prompt,
        )
        self.assertNotIn('"지금/현재 X"는 GPS가 우선이므로 null', prompt)

    @patch("llm_service.parse_intent")
    def test_parse_user_intent_delegates_to_freeze_parser(self, mock_parse_intent):
        intent = {
            "start_location_text": "사당",
            "target_location_text": "잠실",
            "target_location_scope": "place",
            "end_location_text": None,
            "start_time": None,
            "end_time": "19:00",
            "start_time_period": None,
            "end_time_period": None,
            "desired_duration_min_minutes": 30,
            "desired_duration_max_minutes": 60,
            "activities": ["cafe"],
            "transport_mode": "auto",
            "companions": [],
            "budget_max": None,
            "budget_preference": None,
            "space_preference": None,
        }
        mock_parse_intent.return_value = intent

        result = parse_user_intent("7시 전에 카페", "2026-09-03T12:00:00+09:00")

        self.assertEqual(result, intent)
        mock_parse_intent.assert_called_once_with(
            "7시 전에 카페",
            runtime_context={
                "current_datetime": "2026-09-03T12:00:00+09:00",
                "timezone": "Asia/Seoul",
            },
        )
        self.assertEqual(StructuredConditions(**result).activities, ["cafe"])

    def test_recommendation_message_uses_result_without_openai(self):
        recommendation_result = {
            "target_area": None,
            "current_area": None,
            "other_areas": [
                {"AREA_NM": "성수동"},
                {"AREA_NM": "서울숲"},
                {"AREA_NM": "건대입구"},
            ],
            "extended_areas": [{"AREA_NM": "잠실"}],
        }

        with patch("openai.OpenAI") as mock_openai:
            message = generate_recommendation_message(
                "카페 추천해줘",
                recommendation_result,
            )

        self.assertEqual(
            message,
            "가장 추천하는 지역은 '성수동'이에요. "
            "다른 선택지로 '서울숲', '건대입구'도 확인해볼 수 있어요. "
            "이동 범위를 넓히면 '잠실'도 확인해볼 수 있어요.",
        )
        mock_openai.assert_not_called()

    def test_recommendation_message_handles_available_result_shapes(self):
        cases = [
            (
                {
                    "target_area": {"AREA_NM": "강남역"},
                    "current_area": None,
                    "other_areas": [],
                    "extended_areas": [],
                },
                "추천 목적 지역은 '강남역'이에요.",
            ),
            (
                {
                    "target_area": None,
                    "current_area": {"AREA_NM": "홍대입구"},
                    "other_areas": [],
                    "extended_areas": [],
                },
                "현재 계신 지역인 '홍대입구'부터 확인해보세요.",
            ),
            (
                {
                    "target_area": None,
                    "current_area": None,
                    "other_areas": [],
                    "extended_areas": [{"AREA_NM": "북촌"}],
                },
                "이동 범위를 넓힌 추천 지역은 '북촌'이에요.",
            ),
            (
                {
                    "target_area": None,
                    "current_area": None,
                    "other_areas": [],
                    "extended_areas": [],
                },
                "현재 조건에서 추천 가능한 지역을 찾지 못했어요.",
            ),
        ]

        for recommendation_result, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    generate_recommendation_message(
                        "사용자 입력은 문구를 바꾸지 않음",
                        recommendation_result,
                    ),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
