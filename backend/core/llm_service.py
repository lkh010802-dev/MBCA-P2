import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from models import StructuredConditions

load_dotenv()

HERE = Path(__file__).resolve().parent
FREEZE_DIR = HERE / "LLM" / "LLM_V1_4_FREEZE"

# Freeze 모듈은 같은 폴더의 파일을 sibling import한다.
sys.path.insert(0, str(FREEZE_DIR))
try:
    from intent_parser import parse_intent
finally:
    sys.path.remove(str(FREEZE_DIR))

def parse_user_intent(
    user_input: str,
    current_datetime: str,
    timezone: str = "Asia/Seoul"
) -> dict:
    """
    사용자의 자연어를 LLM으로 분석하여
    LLM V1.3.1 resilience freeze의 16개 필드 JSON으로 변환한다.
    """
    return parse_intent(
        user_input,
        runtime_context={
            "current_datetime": current_datetime,
            "timezone": timezone,
        },
    )


if __name__ == "__main__":
    test_input = "지금 사당인데 7시에 잠실 약속 있어. 그사이에 카페 가고 싶어."

    test_datetime = "2026-08-31T12:48:00+09:00"

    result = parse_user_intent(
        user_input=test_input,
        current_datetime=test_datetime
    )

    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2
    ))

    conditions = StructuredConditions(**result)

    print("\n=== StructuredConditions 변환 결과 ===")
    print(conditions.model_dump())


def generate_recommendation_message(
    user_message: str,
    recommendation_result: dict
):
    """
    백엔드가 계산한 추천 결과를 이용해
    사용자에게 보여줄 결정적인 추천 문장을 생성한다.
    """
    del user_message

    target_area = recommendation_result.get("target_area")
    current_area = recommendation_result.get("current_area")
    other_areas = recommendation_result.get("other_areas") or []
    extended_areas = recommendation_result.get("extended_areas") or []
    messages = []

    if target_area:
        messages.append(
            f"추천 목적 지역은 '{target_area['AREA_NM']}'이에요."
        )
    elif current_area:
        messages.append(
            f"현재 계신 지역인 '{current_area['AREA_NM']}'부터 확인해보세요."
        )
    elif other_areas:
        messages.append(
            f"가장 추천하는 지역은 '{other_areas[0]['AREA_NM']}'이에요."
        )
        other_areas = other_areas[1:]
    elif extended_areas:
        messages.append(
            f"이동 범위를 넓힌 추천 지역은 '{extended_areas[0]['AREA_NM']}'이에요."
        )
        extended_areas = extended_areas[1:]
    else:
        return "현재 조건에서 추천 가능한 지역을 찾지 못했어요."

    if other_areas:
        names = ", ".join(
            f"'{area['AREA_NM']}'" for area in other_areas
        )
        messages.append(f"다른 선택지로 {names}도 확인해볼 수 있어요.")

    if extended_areas:
        names = ", ".join(
            f"'{area['AREA_NM']}'" for area in extended_areas
        )
        messages.append(
            f"이동 범위를 넓히면 {names}도 확인해볼 수 있어요."
        )

    return " ".join(messages)
