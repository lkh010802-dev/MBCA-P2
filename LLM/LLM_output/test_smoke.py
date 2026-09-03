"""
간단 스모크 테스트.
실제 OpenAI API를 호출하므로 .env의 OPENAI_API_KEY가 필요합니다.
"""

from llm_output import generate_course_message


TEST_CASES = [
    {
        "name": "FEASIBLE_2_places",
        "data": {
            "optimized_places": [
                {"name": "A카페"},
                {"name": "B전시관"},
            ],
            "total_required_minutes": 140,
            "available_time_minutes": 180,
            "remaining_time_minutes": 40,
            "status": "FEASIBLE",
        },
    },
    {
        "name": "FEASIBLE_single",
        "data": {
            "optimized_places": [
                {"name": "서울숲 산책로"},
            ],
            "total_required_minutes": 75,
            "available_time_minutes": 120,
            "remaining_time_minutes": 45,
            "status": "FEASIBLE",
        },
    },
    {
        "name": "FEASIBLE_zero",
        "data": {
            "optimized_places": [
                {"name": "연남동 식당"},
                {"name": "독립서점"},
            ],
            "total_required_minutes": 120,
            "available_time_minutes": 120,
            "remaining_time_minutes": 0,
            "status": "FEASIBLE",
        },
    },
    {
        "name": "INFEASIBLE",
        "data": {
            "optimized_places": [
                {"name": "홍대 맛집"},
                {"name": "팝업스토어"},
                {"name": "연남동 카페"},
            ],
            "total_required_minutes": 230,
            "available_time_minutes": 180,
            "remaining_time_minutes": -50,
            "status": "INFEASIBLE",
        },
    },
]


for case in TEST_CASES:
    print("=" * 80)
    print(case["name"])
    message, meta = generate_course_message(
        case["data"],
        return_meta=True,
    )
    print(message)
    print(
        f"retry={meta['retry_used']} "
        f"fallback={meta['fallback_used']} "
        f"route_mode={meta['route_mode']}"
    )
