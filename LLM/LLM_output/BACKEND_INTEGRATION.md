# 백엔드 연동 설명서

## 1. 전체 흐름

```text
사용자 입력
  ↓
기존 사용자 입력 분석 LLM
  ↓
백엔드 추천/랭킹
  ↓
사용자 장소 선택
  ↓
백엔드 이동시간 계산 및 방문 순서 최적화
  ↓
백엔드 FEASIBLE / INFEASIBLE 최종 판정
  ↓
generate_course_message(course_result)
  ↓
사용자용 자연어 안내
```

최종 자연어 LLM은 **백엔드의 계산 결과를 설명하는 역할만 수행**합니다.

---

## 2. 연동 함수

```python
from koala_llm_output import generate_course_message
```

### 기본 호출

```python
message = generate_course_message(course_result)
```

### 디버깅 메타 포함

```python
message, meta = generate_course_message(
    course_result,
    return_meta=True,
)
```

---

## 3. 필수 입력 필드

`course_result`에서 실제 자연어 생성에 사용하는 필드는 다음과 같습니다.

### `optimized_places`

배열의 순서 자체가 최종 방문 순서입니다.

최소한 각 객체의 `name`이 필요합니다.

```json
{
  "optimized_places": [
    {"name": "A카페"},
    {"name": "B전시관"}
  ]
}
```

`category`, `latitude`, `longitude`, `specified_duration_minutes` 등의 추가 필드가 있어도 그대로 전달해도 됩니다. 자연어 출력 모듈 내부에서 필요한 필드만 추립니다.

### `total_required_minutes`

백엔드에서 계산한 총 필요시간입니다.

### `available_time_minutes`

사용자가 일정에 사용할 수 있는 전체 시간입니다.

### `remaining_time_minutes`

백엔드 계산 결과를 그대로 전달합니다.

- FEASIBLE: `0` 이상
- INFEASIBLE: 음수

예:

```text
40   → 40분 남음
0    → 정확히 맞음
-30  → 30분 부족
```

LLM이 직접 계산하지 않습니다.

### `status`

허용값:

```text
FEASIBLE
INFEASIBLE
```

---

## 4. FastAPI 예시

백엔드 서비스 내부에서 `/recommend/course` 계산이 끝난 뒤:

```python
from koala_llm_output import generate_course_message


@app.post("/recommend/course")
async def recommend_course(...):
    course_result = ...  # 기존 코스 계산 로직

    course_result["message"] = generate_course_message(
        course_result
    )

    return course_result
```

예를 들어 최종 응답에 아래처럼 `message` 필드만 추가할 수 있습니다.

```json
{
  "optimized_places": [
    {"name": "A카페"},
    {"name": "B전시관"}
  ],
  "total_required_minutes": 140,
  "available_time_minutes": 180,
  "remaining_time_minutes": 40,
  "status": "FEASIBLE",
  "message": "오늘은 A카페 → B전시관 순으로 둘러보게 돼요. 전체 일정에는 약 140분이 필요하고, 사용할 수 있는 180분 중 약 40분이 남아요."
}
```

API 응답 구조를 변경하고 싶지 않으면 별도 service layer에서 `message`만 반환하도록 구성해도 됩니다.

---

## 5. 내부 안전장치

### Placeholder

장소/숫자는 LLM에게 실제 값으로 전달하지 않습니다.

LLM에는 아래처럼 placeholder만 전달합니다.

```text
{{ROUTE}}
{{TOTAL_REQUIRED}}
{{AVAILABLE}}
{{REMAINING}}
{{SHORTAGE}}
```

LLM 호출 종료 후 실제 백엔드 값으로 치환합니다.

### Validation

다음을 자동 확인합니다.

- 필요한 placeholder 누락
- placeholder 중복
- 사용하면 안 되는 placeholder 포함
- placeholder 단계에서 실제 장소명 직접 생성

### Retry

Validation 실패 시 `gpt-5-nano`를 1회 재호출합니다.

### Fallback

재호출 후에도 validation에 실패하면 코드에 정의된 안전한 고정 템플릿을 사용합니다.

따라서 LLM 오류 때문에 사용자 응답 자체가 사라지는 것을 방지합니다.

---

## 6. 환경 변수

```env
OPENAI_API_KEY=...
KOALA_OUTPUT_MODEL=gpt-5-nano
KOALA_OUTPUT_MAX_TOKENS=250
```

`KOALA_OUTPUT_MODEL`을 따로 지정하지 않으면 `gpt-5-nano`를 사용합니다.

---

## 7. 예외

다음 경우 `ValueError`가 발생합니다.

- `optimized_places`가 비어 있음
- 필수 시간 필드 누락
- `status`가 `FEASIBLE / INFEASIBLE`가 아님

OpenAI API 장애/인증 오류 같은 외부 호출 예외는 현재 상위 백엔드 레이어로 전달됩니다.

운영 환경에서는 해당 예외를 백엔드 공통 예외 처리 정책에 맞춰 처리하면 됩니다.

---

## 8. 현재 테스트 결과

개발 중 사용한 테스트 세트:

- FEASIBLE 10건
- INFEASIBLE 10건
- 장소 1개
- 장소 2~5개
- 남는 시간 0분 / 3분 / 큰 여유
- 부족 시간 1분 / 10분 / 120분
- 긴 장소명
- `specified_duration_minutes = null`

최종 테스트에서:

```text
전체 테스트       : 20
최종 검증 통과    : 20
nano 재호출 발생  : 0
fallback 사용     : 0
```

이 결과는 개발 테스트 결과이며, 실제 운영 데이터 연결 후 추가 테스트를 권장합니다.

---

## 9. 백엔드에서 기억할 핵심

```text
코스 계산/판단 = 백엔드
자연어 표현     = LLM
```

LLM 출력으로 다음 값을 다시 수정하면 안 됩니다.

- 방문 순서
- 이동시간
- 체류시간
- 총 필요시간
- 남은/부족 시간
- FEASIBLE / INFEASIBLE
