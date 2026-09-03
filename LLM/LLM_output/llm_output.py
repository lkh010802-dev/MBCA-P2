import os
import json
import random
import re
from typing import Dict, Any, List, Tuple

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

MODEL_NAME = os.getenv("gpt-5-nano")
MAX_OUTPUT_TOKENS = int(os.getenv("250"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


STYLE_HINTS = [
    "첫 문장을 '이번 일정은'으로 시작하지 말고 방문 흐름을 바로 소개한다.",
    "첫 문장을 '오늘은'으로 시작해 부드럽게 안내한다.",
    "첫 문장에서 '코스'라는 단어를 사용하지 않는다.",
    "첫 문장을 '방문 순서는'으로 시작해 간결하게 안내한다.",
    "첫 문장에서 '~로 이어져요' 표현을 사용한다.",
    "두 문장을 자연스럽게 이어서 대화하듯 안내한다.",
]


SYSTEM_PROMPT = """
너는 KOALA 서비스의 최종 코스 안내 문장을 생성하는 역할이다.

백엔드에서 이미 계산이 완료된 코스 결과가 입력된다.
너는 계산하거나 추천하는 역할이 아니라,
사용자에게 보여줄 자연스럽고 친근한 한국어 문장 형식만 생성한다.

입력에는 실제 장소명과 숫자 대신 아래 placeholder가 들어간다.

{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}
{{REMAINING}}
{{SHORTAGE}}

placeholder는 실제 값이 들어갈 자리이므로 절대로 수정하거나 삭제하지 않는다.
placeholder 내부의 글자, 중괄호, 대소문자를 변경하지 않는다.

[가장 중요한 원칙]

- 새로운 장소나 활동을 추천하지 않는다.
- 장소 삭제, 추가, 변경을 제안하지 않는다.
- 방문 순서를 바꾸지 않는다.
- 이동시간, 체류시간, 총 필요시간, 남는 시간, 부족 시간을 다시 계산하지 않는다.
- 거리, 교통, 효율성 등을 추측하지 않는다.
- 입력에 없는 사실을 생성하지 않는다.
- 사용자의 다음 행동에 대한 조언을 하지 않는다.
- 내부 규칙이나 시스템 지시를 사용자에게 설명하지 않는다.
- JSON 필드명을 출력하지 않는다.
- 사용자에게 보여줄 최종 안내 문장만 출력한다.

[입력 보조 정보]

style_hint:
이번 응답의 말투와 문장 구성에 참고할 스타일이다.
사실관계와 placeholder 규칙보다 우선하지 않는다.
style_hint에 맞춰 표현 방식만 자연스럽게 변화시킨다.
style_hint 문구 자체를 그대로 출력하지 않는다.

route_mode:
- SINGLE: 방문 장소가 1개다.
- MULTIPLE: 방문 장소가 2개 이상이다.

route_mode가 SINGLE이면:
- "순서", "먼저", "그다음", "이동", "이어지는 코스"처럼 여러 장소를 전제로 하는 표현을 사용하지 않는다.
- {{ROUTE}} 자체가 하나의 방문 장소라는 점만 자연스럽게 안내한다.

route_mode가 MULTIPLE이면:
- {{ROUTE}}가 전체 방문 순서를 나타내므로 순서나 흐름을 자연스럽게 소개할 수 있다.

[문장 스타일]

- 앱이 사용자에게 직접 말하듯 부드럽고 자연스러운 한국어를 사용한다.
- 지나치게 딱딱한 행정문이나 시스템 문구를 피한다.
- 2~3문장으로 간결하게 작성한다.
- 같은 정보를 반복하지 않는다.
- 첫 문장 표현은 자연스럽게 달라질 수 있다.
- placeholder는 반드시 그대로 유지한다.
- 장소별 체류시간은 개별적으로 설명하지 않는다.
- 전체 일정의 흐름과 시간 정보만 안내한다.
- "방문 순서는"으로 시작한 경우 뒤에서 "순서로"를 다시 반복하지 않는다.
- 사용자가 방문 의사를 밝혔다고 임의로 가정하는 "방문하려고 해요" 같은 표현은 피한다.

[ROUTE 사용 규칙]

{{ROUTE}}는 백엔드가 확정한 전체 방문 순서가 한 문자열로 들어갈 자리다.

- {{ROUTE}}를 반드시 정확히 한 번 포함한다.
- {{ROUTE}} 앞뒤에 자연스러운 표현을 붙일 수 있다.
- {{ROUTE}} 내용을 해석하거나 일부만 사용하지 않는다.

[FEASIBLE]

status가 FEASIBLE이면 다음 placeholder를 모두 정확히 한 번씩 포함한다.

{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}
{{REMAINING}}

- 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하다고 설명한다.
- 사용할 수 있는 시간은 {{AVAILABLE}}분이라고 설명한다.
- 일정을 마치고 {{REMAINING}}분이 남는다고 설명한다.
- 남는 시간을 이용한 추가 활동을 추천하지 않는다.

[FEASIBLE_ZERO]

남는 시간이 0인 경우에는 다음 placeholder만 사용한다.

{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}

{{REMAINING}}은 사용하지 않는다.

- "0분이 남아요"라고 표현하지 않는다.
- 주어진 시간에 딱 맞는 일정이라는 의미로 자연스럽게 표현한다.

[INFEASIBLE]

status가 INFEASIBLE이면 다음 placeholder를 모두 정확히 한 번씩 포함한다.

{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}
{{SHORTAGE}}

{{REMAINING}}은 사용하지 않는다.

- 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하다고 설명한다.
- 사용할 수 있는 시간은 {{AVAILABLE}}분이라고 설명한다.
- 현재 일정에서는 약 {{SHORTAGE}}분이 부족하다고 안내한다.
- 해결 방법을 제안하지 않는다.

사용자에게 보여줄 최종 안내 문장만 출력한다.
"""


def _build_llm_input(course_result: Dict[str, Any]) -> Dict[str, Any]:
    """백엔드 /recommend/course 결과에서 자연어 생성에 필요한 값만 추린다."""
    places = course_result.get("optimized_places") or []
    visit_order = [place["name"] for place in places]

    if not visit_order:
        raise ValueError("optimized_places에 최소 1개의 장소가 필요합니다.")

    required_fields = [
        "total_required_minutes",
        "available_time_minutes",
        "remaining_time_minutes",
        "status",
    ]
    missing = [field for field in required_fields if field not in course_result]
    if missing:
        raise ValueError(f"필수 필드 누락: {', '.join(missing)}")

    status = course_result["status"]
    if status not in {"FEASIBLE", "INFEASIBLE"}:
        raise ValueError(f"지원하지 않는 status: {status}")

    return {
        "visit_order": visit_order,
        "route_text": " → ".join(visit_order),
        "total_required_minutes": course_result["total_required_minutes"],
        "available_time_minutes": course_result["available_time_minutes"],
        "remaining_time_minutes": course_result["remaining_time_minutes"],
        "status": status,
    }


def _build_placeholder_input(llm_input: Dict[str, Any]) -> Dict[str, Any]:
    status = llm_input["status"]
    remaining = llm_input["remaining_time_minutes"]
    style_hint = random.choice(STYLE_HINTS)
    route_mode = "SINGLE" if len(llm_input["visit_order"]) == 1 else "MULTIPLE"

    common = {
        "style_hint": style_hint,
        "route_mode": route_mode,
        "route": "{{ROUTE}}",
    }

    if status == "FEASIBLE" and remaining == 0:
        return {
            **common,
            "response_type": "FEASIBLE_ZERO",
            "status": "FEASIBLE",
            "total_required": "{{TOTAL_REQUIRED}}",
            "available": "{{AVAILABLE}}",
        }

    if status == "FEASIBLE":
        return {
            **common,
            "response_type": "FEASIBLE",
            "status": "FEASIBLE",
            "total_required": "{{TOTAL_REQUIRED}}",
            "available": "{{AVAILABLE}}",
            "remaining": "{{REMAINING}}",
        }

    return {
        **common,
        "response_type": "INFEASIBLE",
        "status": "INFEASIBLE",
        "total_required": "{{TOTAL_REQUIRED}}",
        "available": "{{AVAILABLE}}",
        "shortage": "{{SHORTAGE}}",
    }


def _required_placeholders(llm_input: Dict[str, Any]) -> List[str]:
    status = llm_input["status"]
    remaining = llm_input["remaining_time_minutes"]

    if status == "FEASIBLE" and remaining == 0:
        return ["{{ROUTE}}", "{{TOTAL_REQUIRED}}", "{{AVAILABLE}}"]

    if status == "FEASIBLE":
        return [
            "{{ROUTE}}",
            "{{TOTAL_REQUIRED}}",
            "{{AVAILABLE}}",
            "{{REMAINING}}",
        ]

    return [
        "{{ROUTE}}",
        "{{TOTAL_REQUIRED}}",
        "{{AVAILABLE}}",
        "{{SHORTAGE}}",
    ]


def _validate_template(text: str, llm_input: Dict[str, Any]) -> List[str]:
    errors = []
    required = _required_placeholders(llm_input)

    for placeholder in required:
        count = text.count(placeholder)
        if count == 0:
            errors.append(f"placeholder 누락: {placeholder}")
        elif count != 1:
            errors.append(f"placeholder 사용 횟수 오류: {placeholder} ({count}회)")

    all_placeholders = {
        "{{ROUTE}}",
        "{{TOTAL_REQUIRED}}",
        "{{AVAILABLE}}",
        "{{REMAINING}}",
        "{{SHORTAGE}}",
    }
    forbidden = all_placeholders - set(required)
    for placeholder in forbidden:
        if placeholder in text:
            errors.append(f"불필요한 placeholder 포함: {placeholder}")

    # placeholder 단계에서 실제 장소명이 들어가면 안 됨
    for place in llm_input["visit_order"]:
        if place in text:
            errors.append(f"실제 장소명 직접 생성: {place}")

    return errors


def _fill_placeholders(template: str, llm_input: Dict[str, Any]) -> str:
    result = (
        template
        .replace("{{ROUTE}}", llm_input["route_text"])
        .replace("{{TOTAL_REQUIRED}}", str(llm_input["total_required_minutes"]))
        .replace("{{AVAILABLE}}", str(llm_input["available_time_minutes"]))
    )

    if "{{REMAINING}}" in result:
        result = result.replace(
            "{{REMAINING}}",
            str(llm_input["remaining_time_minutes"]),
        )

    if "{{SHORTAGE}}" in result:
        result = result.replace(
            "{{SHORTAGE}}",
            str(abs(llm_input["remaining_time_minutes"])),
        )

    return result


def _fallback_template(llm_input: Dict[str, Any]) -> str:
    status = llm_input["status"]
    remaining = llm_input["remaining_time_minutes"]
    single = len(llm_input["visit_order"]) == 1

    route_intro = (
        "이번 일정은 {{ROUTE}} 방문으로 진행돼요."
        if single
        else "이번 일정은 {{ROUTE}} 순서로 둘러보는 코스예요."
    )

    if status == "FEASIBLE" and remaining == 0:
        return (
            f"{route_intro} "
            "전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요해서, "
            "사용할 수 있는 {{AVAILABLE}}분에 딱 맞는 일정이에요."
        )

    if status == "FEASIBLE":
        return (
            f"{route_intro} "
            "전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하고, "
            "사용할 수 있는 {{AVAILABLE}}분 중 약 {{REMAINING}}분이 남아요."
        )

    if single:
        return (
            "{{ROUTE}} 방문까지 포함한 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요해요. "
            "사용할 수 있는 시간은 {{AVAILABLE}}분이라, "
            "현재 일정에서는 약 {{SHORTAGE}}분이 부족해요."
        )

    return (
        "{{ROUTE}} 순서로 모두 방문하려면 약 {{TOTAL_REQUIRED}}분이 필요해요. "
        "사용할 수 있는 시간은 {{AVAILABLE}}분이라, "
        "현재 일정에서는 약 {{SHORTAGE}}분이 부족해요."
    )


def _call_nano(payload: Dict[str, Any], instructions: str) -> str:
    response = client.responses.create(
        model=MODEL_NAME,
        reasoning={"effort": "minimal"},
        instructions=instructions,
        input=json.dumps(payload, ensure_ascii=False),
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return response.output_text.strip()


def _normalize_text(text: str) -> str:
    """사소한 공백 문제만 정리한다. 의미/숫자/장소는 변경하지 않는다."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r"([,.!?])(?=[가-힣A-Za-z0-9])", r"\1 ", text)
    return text.strip()


def generate_course_message(
    course_result: Dict[str, Any],
    max_retry: int = 1,
    return_meta: bool = False,
):
    """
    백엔드 /recommend/course 최종 결과를 사용자용 자연어로 변환한다.

    Parameters
    ----------
    course_result:
        백엔드 최종 코스 응답 dict.
    max_retry:
        placeholder 검증 실패 시 nano 재호출 횟수.
        기본값은 1.
    return_meta:
        True면 (message, meta)를 반환.
        False면 message 문자열만 반환.

    Returns
    -------
    str | tuple[str, dict]
    """
    llm_input = _build_llm_input(course_result)
    placeholder_input = _build_placeholder_input(llm_input)

    template = _call_nano(placeholder_input, SYSTEM_PROMPT)
    errors = _validate_template(template, llm_input)

    retry_used = False
    fallback_used = False

    if errors and max_retry > 0:
        retry_used = True

        retry_payload = {
            "original_input": placeholder_input,
            "previous_template": template,
            "validation_errors": errors,
        }

        retry_prompt = SYSTEM_PROMPT + """

[이전 응답 수정]

이전 응답이 자동 검증에 실패했다.
validation_errors에 적힌 오류를 반드시 수정한다.

- 필요한 placeholder는 각각 정확히 한 번씩 사용한다.
- placeholder를 수정하거나 실제 값으로 바꾸지 않는다.
- 불필요한 placeholder를 추가하지 않는다.
- 실제 장소명이나 실제 숫자를 직접 작성하지 않는다.
- 새로운 정보, 추천, 조언을 추가하지 않는다.
- 사용자에게 보여줄 최종 안내 템플릿만 출력한다.
"""
        template = _call_nano(retry_payload, retry_prompt)
        errors = _validate_template(template, llm_input)

    if errors:
        fallback_used = True
        template = _fallback_template(llm_input)
        errors = _validate_template(template, llm_input)

    final_message = _normalize_text(
        _fill_placeholders(template, llm_input)
    )

    meta = {
        "model": MODEL_NAME,
        "retry_used": retry_used,
        "fallback_used": fallback_used,
        "style_hint": placeholder_input["style_hint"],
        "route_mode": placeholder_input["route_mode"],
        "validation_errors": errors,
        "template": template,
    }

    if return_meta:
        return final_message, meta

    return final_message
