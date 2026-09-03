# KOALA 최종 코스 자연어 출력 LLM

백엔드 `/recommend/course`의 최종 계산 결과를 받아 사용자에게 보여줄 자연스러운 한국어 안내 문장으로 변환하는 모듈입니다.

## 1. 역할 분리

이 모듈은 **코스를 계산하지 않습니다.**

백엔드에서 이미 결정된 다음 값을 그대로 사용합니다.

- 방문 장소 및 방문 순서
- 총 필요시간
- 이용 가능시간
- 남는 시간 / 부족 시간
- `FEASIBLE` / `INFEASIBLE`

LLM은 위 결과의 **표현만 자연어로 생성**합니다.

## 2. 핵심 설계

실제 장소명과 숫자를 LLM에 직접 생성시키지 않고 placeholder를 사용합니다.

예:

```text
{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}
{{REMAINING}}
{{SHORTAGE}}
```

LLM은 문장 구조만 생성하고, 호출이 끝난 뒤 Python 코드가 백엔드 실제 값으로 치환합니다.

따라서 다음 오류를 줄이도록 설계되어 있습니다.

- 장소 누락
- 방문 순서 변경
- 숫자 변경
- 음수 부족시간 직접 노출
- 백엔드에 없는 추가 추천

LLM이 placeholder 규칙을 위반하면 1회 재호출하고, 그래도 실패하면 안전한 fallback 템플릿을 사용합니다.

## 3. 파일 구성

```text
koala_llm_output_package/
├─ koala_llm_output.py      # 실제 백엔드 연동용 모듈
├─ example_usage.py         # 간단 연동 예시
├─ test_smoke.py            # API 스모크 테스트
├─ requirements.txt
├─ .env.example
├─ README.md
└─ BACKEND_INTEGRATION.md
```

## 4. 설치

```bash
pip install -r requirements.txt
```

`.env.example`을 참고해서 프로젝트 `.env`에 OpenAI API Key를 설정합니다.

```env
OPENAI_API_KEY=your_openai_api_key
KOALA_OUTPUT_MODEL=gpt-5-nano
KOALA_OUTPUT_MAX_TOKENS=250
```

기본 모델은 `gpt-5-nano`입니다.

## 5. 가장 간단한 사용법

```python
from koala_llm_output import generate_course_message

message = generate_course_message(course_result)
```

`course_result`에는 백엔드 `/recommend/course` 최종 응답 dict를 그대로 넣으면 됩니다.

예:

```python
course_result = {
    "optimized_places": [
        {"name": "A카페"},
        {"name": "B전시관"},
    ],
    "total_required_minutes": 140,
    "available_time_minutes": 180,
    "remaining_time_minutes": 40,
    "status": "FEASIBLE",
}

message = generate_course_message(course_result)
print(message)
```

예상 형태:

```text
오늘은 A카페 → B전시관 순으로 둘러보게 돼요. 전체 일정에는 약 140분이 필요하고, 사용할 수 있는 180분 중 약 40분이 남아요.
```

실제 표현은 style hint에 따라 조금 달라질 수 있습니다.

## 6. 디버깅 정보가 필요한 경우

```python
message, meta = generate_course_message(
    course_result,
    return_meta=True,
)

print(message)
print(meta)
```

`meta`에는 다음 정보가 포함됩니다.

- 사용 모델
- nano 재호출 여부
- fallback 사용 여부
- 선택된 style hint
- `SINGLE / MULTIPLE` route mode
- 최종 validation error

## 7. 주의사항

LLM 결과를 다시 코스 계산에 사용하지 마세요.

이 모듈의 반환값은 **사용자 화면에 표시할 설명 문장**입니다. 실제 코스 데이터의 source of truth는 항상 백엔드 `/recommend/course` 결과입니다.
