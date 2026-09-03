# KOALA 최종 코스 자연어 생성 테스트 v3.1
# - placeholder 기반 정확성 보장
# - style_hint 기반 문체 다양화
# - SINGLE/MULTIPLE 방문 형태 구분

import os
import json
import random

from dotenv import load_dotenv
from openai import OpenAI


# =========================================================
# 환경 설정
# =========================================================
load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


# =========================================================
# 응답 문체 힌트
# 사실관계는 그대로 유지하고 표현 방식만 조금씩 바꾼다.
# =========================================================
STYLE_HINTS = [
    "일정을 소개하듯 편안하고 자연스럽게",
    "친근하고 가볍지만 과하지 않게",
    "방문 흐름을 자연스럽게 소개하듯",
    "간결하지만 딱딱하지 않게",
    "데이트 코스를 안내하듯 부드럽게",
    "앱이 사용자에게 친근하게 알려주듯",
]


# =========================================================
# System Prompt
# =========================================================
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
- 예: "이번 일정은 {{ROUTE}} 방문으로 진행돼요."

route_mode가 MULTIPLE이면:
- {{ROUTE}}가 전체 방문 순서를 나타내므로 순서나 흐름을 자연스럽게 소개할 수 있다.

[문장 스타일]

- 앱이 사용자에게 직접 말하듯 부드럽고 자연스러운 한국어를 사용한다.
- 지나치게 딱딱한 행정문이나 시스템 문구를 피한다.
- "계획이 잡혀 있습니다", "최적화된 결과입니다", "구성되어 있습니다" 같은 표현은 피한다.
- 2문장 정도로 간결하게 작성한다.
- 같은 정보를 반복하지 않는다.
- 첫 문장 표현은 매번 자연스럽게 달라질 수 있다.
- 다만 placeholder는 반드시 그대로 유지한다.
- 장소별 체류시간은 개별적으로 설명하지 않는다.
- 전체 일정의 흐름과 시간 정보만 안내한다.

[ROUTE 사용 규칙]

{{ROUTE}}는 백엔드가 확정한 전체 방문 순서가 한 문자열로 들어갈 자리다.

- {{ROUTE}}를 반드시 정확히 한 번 포함한다.
- {{ROUTE}} 앞뒤에 자연스러운 표현을 붙일 수 있다.
- {{ROUTE}} 내용을 해석하거나 일부만 사용하지 않는다.
- 장소가 몇 개인지 추측하지 않는다.

좋은 표현 예:

route_mode가 MULTIPLE일 때:
- 이번 일정은 {{ROUTE}} 순서로 둘러보는 코스예요.
- {{ROUTE}} 순서로 이어지는 일정이에요.
- 오늘은 {{ROUTE}} 흐름으로 방문하게 돼요.
- 방문 순서는 {{ROUTE}}로 이어져요.

route_mode가 SINGLE일 때:
- 이번 일정은 {{ROUTE}} 방문으로 진행돼요.
- 오늘 일정에서는 {{ROUTE}}를 중심으로 둘러보게 돼요.
- 이번 코스의 방문지는 {{ROUTE}} 한 곳이에요.

[FEASIBLE]

status가 FEASIBLE이면 다음 placeholder를 모두 정확히 한 번씩 포함한다.

{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}
{{REMAINING}}

- 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하다고 설명한다.
- 사용할 수 있는 시간은 {{AVAILABLE}}분이라고 설명한다.
- 일정을 마치고 {{REMAINING}}분이 남는다고 설명한다.
- {{REMAINING}} 값 자체를 평가하거나 새로운 활동을 추천하지 않는다.

좋은 예:
이번 일정은 {{ROUTE}} 순서로 둘러보는 코스예요. 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하고, 사용할 수 있는 {{AVAILABLE}}분 중 약 {{REMAINING}}분이 남아요.

{{ROUTE}} 순서로 이어지는 일정이에요. 모두 둘러보는 데 약 {{TOTAL_REQUIRED}}분이 필요해서, 주어진 {{AVAILABLE}}분 중 약 {{REMAINING}}분의 시간이 남아요.

[FEASIBLE_ZERO]

남는 시간이 0인 경우에는 다음 placeholder만 사용한다.

{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}

{{REMAINING}}은 사용하지 않는다.

- "0분이 남아요"라고 표현하지 않는다.
- 주어진 시간에 딱 맞는 일정이라는 의미로 자연스럽게 표현한다.

좋은 예:
이번 일정은 {{ROUTE}} 순서로 진행돼요. 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요해서, 사용할 수 있는 {{AVAILABLE}}분에 딱 맞는 일정이에요.

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
- 해결 방법은 제안하지 않는다.

좋은 예:
{{ROUTE}} 순서로 모두 방문하려면 약 {{TOTAL_REQUIRED}}분이 필요해요. 사용할 수 있는 시간은 {{AVAILABLE}}분이라, 현재 일정에서는 약 {{SHORTAGE}}분이 부족해요.

이번 코스는 {{ROUTE}} 순서로 이어져요. 전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하지만 사용할 수 있는 시간은 {{AVAILABLE}}분이라, 약 {{SHORTAGE}}분이 부족해요.

사용자에게 보여줄 최종 안내 문장만 출력한다.
"""


# =========================================================
# 백엔드 결과 -> LLM 입력 데이터
# =========================================================
def build_llm_input(course_result):
    visit_order = [
        place["name"]
        for place in course_result["optimized_places"]
    ]

    return {
        "visit_order": visit_order,
        "route_text": " → ".join(visit_order),
        "total_required_minutes": course_result["total_required_minutes"],
        "available_time_minutes": course_result["available_time_minutes"],
        "remaining_time_minutes": course_result["remaining_time_minutes"],
        "status": course_result["status"],
    }


# =========================================================
# Placeholder 템플릿 생성
# =========================================================
def build_placeholder_input(llm_input):
    status = llm_input["status"]
    remaining = llm_input["remaining_time_minutes"]

    style_hint = random.choice(STYLE_HINTS)

    route_mode = (
        "SINGLE"
        if len(llm_input["visit_order"]) == 1
        else "MULTIPLE"
    )

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


# =========================================================
# 필요한 Placeholder 목록
# =========================================================
def required_placeholders(llm_input):
    status = llm_input["status"]
    remaining = llm_input["remaining_time_minutes"]

    if status == "FEASIBLE" and remaining == 0:
        return [
            "{{ROUTE}}",
            "{{TOTAL_REQUIRED}}",
            "{{AVAILABLE}}",
        ]

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


# =========================================================
# LLM 템플릿 검증
# =========================================================
def validate_template(text, llm_input):
    errors = []

    required = required_placeholders(llm_input)

    # 1. 필요한 placeholder 누락 여부
    missing = [
        placeholder
        for placeholder in required
        if placeholder not in text
    ]

    if missing:
        errors.append(
            "placeholder 누락: " + ", ".join(missing)
        )

    # 2. 필요한 placeholder가 정확히 1번씩 등장하는지 확인
    duplicated = [
        placeholder
        for placeholder in required
        if text.count(placeholder) != 1
    ]

    if duplicated:
        errors.append(
            "placeholder 사용 횟수 오류: " + ", ".join(duplicated)
        )

    # 3. 현재 응답 타입에서 사용하면 안 되는 placeholder 확인
    all_placeholders = {
        "{{ROUTE}}",
        "{{TOTAL_REQUIRED}}",
        "{{AVAILABLE}}",
        "{{REMAINING}}",
        "{{SHORTAGE}}",
    }

    forbidden = all_placeholders - set(required)

    exposed_forbidden = [
        placeholder
        for placeholder in forbidden
        if placeholder in text
    ]

    if exposed_forbidden:
        errors.append(
            "불필요한 placeholder 포함: " + ", ".join(exposed_forbidden)
        )

    # 4. 실제 숫자나 장소명이 placeholder 단계에서 미리 들어가면 안 됨
    for place in llm_input["visit_order"]:
        if place in text:
            errors.append(
                f"실제 장소명 직접 생성: {place}"
            )

    actual_numbers = [
        str(llm_input["total_required_minutes"]),
        str(llm_input["available_time_minutes"]),
        str(abs(llm_input["remaining_time_minutes"])),
    ]

    for number in actual_numbers:
        if number and number in text:
            errors.append(
                f"실제 숫자 직접 생성: {number}"
            )

    return list(dict.fromkeys(errors))


# =========================================================
# Placeholder 실제 값 치환
# =========================================================
def fill_placeholders(template, llm_input):
    result = template

    result = result.replace(
        "{{ROUTE}}",
        llm_input["route_text"]
    )

    result = result.replace(
        "{{TOTAL_REQUIRED}}",
        str(llm_input["total_required_minutes"])
    )

    result = result.replace(
        "{{AVAILABLE}}",
        str(llm_input["available_time_minutes"])
    )

    if "{{REMAINING}}" in result:
        result = result.replace(
            "{{REMAINING}}",
            str(llm_input["remaining_time_minutes"])
        )

    if "{{SHORTAGE}}" in result:
        result = result.replace(
            "{{SHORTAGE}}",
            str(abs(llm_input["remaining_time_minutes"]))
        )

    return result


# =========================================================
# Fallback 템플릿
# LLM이 placeholder 규칙을 계속 위반할 때 사용
# =========================================================
def build_fallback_template(llm_input):
    status = llm_input["status"]
    remaining = llm_input["remaining_time_minutes"]

    if len(llm_input["visit_order"]) == 1:
        route_sentence = "이번 일정은 {{ROUTE}} 방문으로 진행돼요."
    else:
        route_sentence = "이번 일정은 {{ROUTE}} 순서로 둘러보는 코스예요."

    if status == "FEASIBLE" and remaining == 0:
        return (
            f"{route_sentence} "
            "전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요해서, "
            "사용할 수 있는 {{AVAILABLE}}분에 딱 맞는 일정이에요."
        )

    if status == "FEASIBLE":
        return (
            f"{route_sentence} "
            "전체 일정에는 약 {{TOTAL_REQUIRED}}분이 필요하고, "
            "사용할 수 있는 {{AVAILABLE}}분 중 약 {{REMAINING}}분이 남아요."
        )

    if len(llm_input["visit_order"]) == 1:
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


# =========================================================
# nano 호출
# =========================================================
def call_nano(placeholder_input, instructions):
    response = client.responses.create(
        model="gpt-5.6-luna",
        reasoning={"effort": "none"},
        instructions=instructions,
        input=json.dumps(
            placeholder_input,
            ensure_ascii=False
        ),
        max_output_tokens=250,
    )

    return response.output_text.strip()


# =========================================================
# 최종 자연어 생성
# =========================================================
def generate_course_message(course_result, max_retry=1):
    llm_input = build_llm_input(course_result)
    placeholder_input = build_placeholder_input(llm_input)

    # 1차 nano 호출
    template = call_nano(
        placeholder_input,
        SYSTEM_PROMPT
    )

    errors = validate_template(
        template,
        llm_input
    )

    retry_used = False
    fallback_used = False

    # 검증 실패 시 nano 1회 재호출
    if errors and max_retry > 0:
        retry_used = True

        retry_input = {
            "original_input": placeholder_input,
            "previous_template": template,
            "validation_errors": errors,
        }

        retry_prompt = SYSTEM_PROMPT + """

[이전 응답 수정]

이전 응답이 자동 검증에 실패했다.
validation_errors에 적힌 오류를 반드시 수정한다.

특히:
- 필요한 placeholder는 각각 정확히 한 번씩 사용한다.
- placeholder를 수정하거나 실제 값으로 바꾸지 않는다.
- 불필요한 placeholder를 추가하지 않는다.
- 실제 장소명이나 실제 숫자를 직접 작성하지 않는다.
- 새로운 정보, 추천, 조언을 추가하지 않는다.
- 사용자에게 보여줄 최종 안내 템플릿만 출력한다.
"""

        template = call_nano(
            retry_input,
            retry_prompt
        )

        errors = validate_template(
            template,
            llm_input
        )

    # 재시도 후에도 실패하면 안전한 fallback 템플릿 사용
    if errors:
        fallback_used = True

        template = build_fallback_template(
            llm_input
        )

        errors = validate_template(
            template,
            llm_input
        )

    # placeholder -> 실제 백엔드 값 치환
    final_message = fill_placeholders(
        template,
        llm_input
    )

    meta = {
        "retry_used": retry_used,
        "fallback_used": fallback_used,
        "template": template,
        "validation_errors": errors,
        "style_hint": placeholder_input["style_hint"],
        "route_mode": placeholder_input["route_mode"],
    }

    return final_message, meta


# =========================================================
# 테스트 케이스
# FEASIBLE 10건 + INFEASIBLE 10건
# =========================================================
test_cases = [

    {
        "test_name": "FEASIBLE_01_기본_2개장소",
        "optimized_places": [
            {
                "name": "A카페",
                "category": "cafe",
                "latitude": 37.5445,
                "longitude": 127.0560,
                "specified_duration_minutes": 45
            },
            {
                "name": "B전시관",
                "category": "culture",
                "latitude": 37.5460,
                "longitude": 127.0430,
                "specified_duration_minutes": 60
            }
        ],
        "total_stay_time_minutes": 105,
        "total_travel_time_minutes": 35,
        "total_required_minutes": 140,
        "available_time_minutes": 180,
        "remaining_time_minutes": 40,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_02_장소1개",
        "optimized_places": [
            {
                "name": "서울숲 산책로",
                "category": "walk",
                "latitude": 37.5444,
                "longitude": 127.0374,
                "specified_duration_minutes": 60
            }
        ],
        "total_stay_time_minutes": 60,
        "total_travel_time_minutes": 15,
        "total_required_minutes": 75,
        "available_time_minutes": 120,
        "remaining_time_minutes": 45,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_03_3개장소",
        "optimized_places": [
            {
                "name": "성수 베이커리",
                "category": "food",
                "latitude": 37.5450,
                "longitude": 127.0540,
                "specified_duration_minutes": 50
            },
            {
                "name": "성수 디자인 전시관",
                "category": "culture",
                "latitude": 37.5430,
                "longitude": 127.0580,
                "specified_duration_minutes": 70
            },
            {
                "name": "루프탑 카페",
                "category": "cafe",
                "latitude": 37.5470,
                "longitude": 127.0520,
                "specified_duration_minutes": 40
            }
        ],
        "total_stay_time_minutes": 160,
        "total_travel_time_minutes": 35,
        "total_required_minutes": 195,
        "available_time_minutes": 240,
        "remaining_time_minutes": 45,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_04_여유3분",
        "optimized_places": [
            {
                "name": "망원시장",
                "category": "food",
                "latitude": 37.5560,
                "longitude": 126.9050,
                "specified_duration_minutes": 60
            },
            {
                "name": "한강공원 산책",
                "category": "walk",
                "latitude": 37.5520,
                "longitude": 126.8990,
                "specified_duration_minutes": 70
            }
        ],
        "total_stay_time_minutes": 130,
        "total_travel_time_minutes": 47,
        "total_required_minutes": 177,
        "available_time_minutes": 180,
        "remaining_time_minutes": 3,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_05_여유0분",
        "optimized_places": [
            {
                "name": "연남동 식당",
                "category": "food",
                "latitude": 37.5610,
                "longitude": 126.9230,
                "specified_duration_minutes": 60
            },
            {
                "name": "독립서점",
                "category": "shopping",
                "latitude": 37.5620,
                "longitude": 126.9250,
                "specified_duration_minutes": 40
            }
        ],
        "total_stay_time_minutes": 100,
        "total_travel_time_minutes": 20,
        "total_required_minutes": 120,
        "available_time_minutes": 120,
        "remaining_time_minutes": 0,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_06_4개장소_순서확인",
        "optimized_places": [
            {
                "name": "브런치 레스토랑",
                "category": "food",
                "latitude": 37.5200,
                "longitude": 127.0220,
                "specified_duration_minutes": 60
            },
            {
                "name": "사진 전시관",
                "category": "culture",
                "latitude": 37.5220,
                "longitude": 127.0250,
                "specified_duration_minutes": 50
            },
            {
                "name": "편집숍",
                "category": "shopping",
                "latitude": 37.5240,
                "longitude": 127.0270,
                "specified_duration_minutes": 35
            },
            {
                "name": "디저트 카페",
                "category": "cafe",
                "latitude": 37.5250,
                "longitude": 127.0300,
                "specified_duration_minutes": 45
            }
        ],
        "total_stay_time_minutes": 190,
        "total_travel_time_minutes": 50,
        "total_required_minutes": 240,
        "available_time_minutes": 300,
        "remaining_time_minutes": 60,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_07_duration_null",
        "optimized_places": [
            {
                "name": "국립현대미술관",
                "category": "culture",
                "latitude": 37.5785,
                "longitude": 126.9800,
                "specified_duration_minutes": None
            },
            {
                "name": "삼청동 카페",
                "category": "cafe",
                "latitude": 37.5820,
                "longitude": 126.9820,
                "specified_duration_minutes": 50
            }
        ],
        "total_stay_time_minutes": 140,
        "total_travel_time_minutes": 30,
        "total_required_minutes": 170,
        "available_time_minutes": 240,
        "remaining_time_minutes": 70,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_08_긴장소명",
        "optimized_places": [
            {
                "name": "서울시립미술관 특별기획전시관",
                "category": "culture",
                "latitude": 37.5640,
                "longitude": 126.9750,
                "specified_duration_minutes": 80
            },
            {
                "name": "덕수궁 돌담길 전망이 보이는 카페",
                "category": "cafe",
                "latitude": 37.5660,
                "longitude": 126.9730,
                "specified_duration_minutes": 50
            }
        ],
        "total_stay_time_minutes": 130,
        "total_travel_time_minutes": 25,
        "total_required_minutes": 155,
        "available_time_minutes": 210,
        "remaining_time_minutes": 55,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_09_5개장소",
        "optimized_places": [
            {
                "name": "을지로 식당",
                "category": "food",
                "latitude": 37.5660,
                "longitude": 126.9910,
                "specified_duration_minutes": 50
            },
            {
                "name": "소규모 사진전",
                "category": "culture",
                "latitude": 37.5650,
                "longitude": 126.9930,
                "specified_duration_minutes": 45
            },
            {
                "name": "빈티지 소품숍",
                "category": "shopping",
                "latitude": 37.5670,
                "longitude": 126.9950,
                "specified_duration_minutes": 30
            },
            {
                "name": "청계천 산책",
                "category": "walk",
                "latitude": 37.5690,
                "longitude": 126.9970,
                "specified_duration_minutes": 40
            },
            {
                "name": "을지로 카페",
                "category": "cafe",
                "latitude": 37.5660,
                "longitude": 126.9990,
                "specified_duration_minutes": 45
            }
        ],
        "total_stay_time_minutes": 210,
        "total_travel_time_minutes": 55,
        "total_required_minutes": 265,
        "available_time_minutes": 300,
        "remaining_time_minutes": 35,
        "status": "FEASIBLE"
    },

    {
        "test_name": "FEASIBLE_10_여유시간많음",
        "optimized_places": [
            {
                "name": "한남동 전시공간",
                "category": "culture",
                "latitude": 37.5350,
                "longitude": 127.0000,
                "specified_duration_minutes": 60
            },
            {
                "name": "한남동 카페",
                "category": "cafe",
                "latitude": 37.5370,
                "longitude": 127.0020,
                "specified_duration_minutes": 40
            }
        ],
        "total_stay_time_minutes": 100,
        "total_travel_time_minutes": 20,
        "total_required_minutes": 120,
        "available_time_minutes": 300,
        "remaining_time_minutes": 180,
        "status": "FEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_01_기본",
        "optimized_places": [
            {
                "name": "A레스토랑",
                "category": "food",
                "latitude": 37.5400,
                "longitude": 127.0500,
                "specified_duration_minutes": 80
            },
            {
                "name": "B전시관",
                "category": "culture",
                "latitude": 37.5450,
                "longitude": 127.0450,
                "specified_duration_minutes": 90
            }
        ],
        "total_stay_time_minutes": 170,
        "total_travel_time_minutes": 40,
        "total_required_minutes": 210,
        "available_time_minutes": 180,
        "remaining_time_minutes": -30,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_02_1분부족",
        "optimized_places": [
            {
                "name": "전시회",
                "category": "culture",
                "latitude": 37.5600,
                "longitude": 126.9800,
                "specified_duration_minutes": 100
            },
            {
                "name": "카페",
                "category": "cafe",
                "latitude": 37.5620,
                "longitude": 126.9820,
                "specified_duration_minutes": 50
            }
        ],
        "total_stay_time_minutes": 150,
        "total_travel_time_minutes": 31,
        "total_required_minutes": 181,
        "available_time_minutes": 180,
        "remaining_time_minutes": -1,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_03_10분부족",
        "optimized_places": [
            {
                "name": "서촌 식당",
                "category": "food",
                "latitude": 37.5790,
                "longitude": 126.9700,
                "specified_duration_minutes": 60
            },
            {
                "name": "서촌 전시공간",
                "category": "culture",
                "latitude": 37.5800,
                "longitude": 126.9720,
                "specified_duration_minutes": 70
            }
        ],
        "total_stay_time_minutes": 130,
        "total_travel_time_minutes": 30,
        "total_required_minutes": 160,
        "available_time_minutes": 150,
        "remaining_time_minutes": -10,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_04_3개장소",
        "optimized_places": [
            {
                "name": "홍대 맛집",
                "category": "food",
                "latitude": 37.5560,
                "longitude": 126.9230,
                "specified_duration_minutes": 70
            },
            {
                "name": "팝업스토어",
                "category": "shopping",
                "latitude": 37.5540,
                "longitude": 126.9250,
                "specified_duration_minutes": 60
            },
            {
                "name": "연남동 카페",
                "category": "cafe",
                "latitude": 37.5620,
                "longitude": 126.9250,
                "specified_duration_minutes": 50
            }
        ],
        "total_stay_time_minutes": 180,
        "total_travel_time_minutes": 50,
        "total_required_minutes": 230,
        "available_time_minutes": 180,
        "remaining_time_minutes": -50,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_05_이동시간김",
        "optimized_places": [
            {
                "name": "북촌 전시관",
                "category": "culture",
                "latitude": 37.5820,
                "longitude": 126.9830,
                "specified_duration_minutes": 60
            },
            {
                "name": "성수 카페",
                "category": "cafe",
                "latitude": 37.5440,
                "longitude": 127.0560,
                "specified_duration_minutes": 50
            }
        ],
        "total_stay_time_minutes": 110,
        "total_travel_time_minutes": 80,
        "total_required_minutes": 190,
        "available_time_minutes": 150,
        "remaining_time_minutes": -40,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_06_duration_null",
        "optimized_places": [
            {
                "name": "대형 미술관",
                "category": "culture",
                "latitude": 37.5250,
                "longitude": 126.9800,
                "specified_duration_minutes": None
            },
            {
                "name": "전망 카페",
                "category": "cafe",
                "latitude": 37.5300,
                "longitude": 126.9850,
                "specified_duration_minutes": 50
            }
        ],
        "total_stay_time_minutes": 170,
        "total_travel_time_minutes": 40,
        "total_required_minutes": 210,
        "available_time_minutes": 180,
        "remaining_time_minutes": -30,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_07_4개장소",
        "optimized_places": [
            {
                "name": "강남 브런치",
                "category": "food",
                "latitude": 37.5000,
                "longitude": 127.0300,
                "specified_duration_minutes": 60
            },
            {
                "name": "복합문화공간",
                "category": "culture",
                "latitude": 37.5020,
                "longitude": 127.0320,
                "specified_duration_minutes": 60
            },
            {
                "name": "쇼핑몰",
                "category": "shopping",
                "latitude": 37.5040,
                "longitude": 127.0350,
                "specified_duration_minutes": 60
            },
            {
                "name": "칵테일바",
                "category": "drink",
                "latitude": 37.5060,
                "longitude": 127.0380,
                "specified_duration_minutes": 60
            }
        ],
        "total_stay_time_minutes": 240,
        "total_travel_time_minutes": 60,
        "total_required_minutes": 300,
        "available_time_minutes": 240,
        "remaining_time_minutes": -60,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_08_120분부족",
        "optimized_places": [
            {
                "name": "놀이공간",
                "category": "entertainment",
                "latitude": 37.5100,
                "longitude": 127.1000,
                "specified_duration_minutes": 150
            },
            {
                "name": "저녁 식당",
                "category": "food",
                "latitude": 37.5150,
                "longitude": 127.1050,
                "specified_duration_minutes": 90
            },
            {
                "name": "야경 산책로",
                "category": "walk",
                "latitude": 37.5200,
                "longitude": 127.1100,
                "specified_duration_minutes": 60
            }
        ],
        "total_stay_time_minutes": 300,
        "total_travel_time_minutes": 60,
        "total_required_minutes": 360,
        "available_time_minutes": 240,
        "remaining_time_minutes": -120,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_09_긴장소명",
        "optimized_places": [
            {
                "name": "서울 현대미술 특별기획 장기전시 공간",
                "category": "culture",
                "latitude": 37.5700,
                "longitude": 126.9800,
                "specified_duration_minutes": 100
            },
            {
                "name": "도심 야경이 보이는 루프탑 디저트 카페",
                "category": "cafe",
                "latitude": 37.5720,
                "longitude": 126.9820,
                "specified_duration_minutes": 70
            }
        ],
        "total_stay_time_minutes": 170,
        "total_travel_time_minutes": 35,
        "total_required_minutes": 205,
        "available_time_minutes": 180,
        "remaining_time_minutes": -25,
        "status": "INFEASIBLE"
    },

    {
        "test_name": "INFEASIBLE_10_5개장소",
        "optimized_places": [
            {
                "name": "시장 먹거리",
                "category": "food",
                "latitude": 37.5700,
                "longitude": 127.0000,
                "specified_duration_minutes": 45
            },
            {
                "name": "독립 전시공간",
                "category": "culture",
                "latitude": 37.5710,
                "longitude": 127.0020,
                "specified_duration_minutes": 50
            },
            {
                "name": "소품숍",
                "category": "shopping",
                "latitude": 37.5720,
                "longitude": 127.0040,
                "specified_duration_minutes": 40
            },
            {
                "name": "공원 산책",
                "category": "walk",
                "latitude": 37.5730,
                "longitude": 127.0060,
                "specified_duration_minutes": 50
            },
            {
                "name": "저녁 카페",
                "category": "cafe",
                "latitude": 37.5740,
                "longitude": 127.0080,
                "specified_duration_minutes": 45
            }
        ],
        "total_stay_time_minutes": 230,
        "total_travel_time_minutes": 70,
        "total_required_minutes": 300,
        "available_time_minutes": 240,
        "remaining_time_minutes": -60,
        "status": "INFEASIBLE"
    },
]


# =========================================================
# 테스트 실행
# =========================================================
if __name__ == "__main__":

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. .env 파일을 확인해주세요."
        )

    success_count = 0
    retry_count = 0
    fallback_count = 0

    for case in test_cases:
        test_name = case["test_name"]

        course_result = {
            k: v
            for k, v in case.items()
            if k != "test_name"
        }

        final_message, meta = generate_course_message(
            course_result
        )

        print("=" * 80)
        print(test_name)
        print("-" * 80)
        print(final_message)
        print()
        print(f"🎨 style_hint: {meta['style_hint']}")
        print(f"🧭 route_mode: {meta['route_mode']}")

        if meta["validation_errors"]:
            print("❌ FINAL VALIDATION FAILED")
            for error in meta["validation_errors"]:
                print(f" - {error}")
        else:
            success_count += 1
            print("✅ FINAL VALIDATION PASSED")

        if meta["retry_used"]:
            retry_count += 1
            print("↻ nano 재호출 사용")

        if meta["fallback_used"]:
            fallback_count += 1
            print("⚠ fallback 템플릿 사용")

        print()

    print("=" * 80)
    print("TEST SUMMARY")
    print("-" * 80)
    print(f"전체 테스트       : {len(test_cases)}")
    print(f"최종 검증 통과    : {success_count}")
    print(f"nano 재호출 발생  : {retry_count}")
    print(f"fallback 사용     : {fallback_count}")
    print("=" * 80)
