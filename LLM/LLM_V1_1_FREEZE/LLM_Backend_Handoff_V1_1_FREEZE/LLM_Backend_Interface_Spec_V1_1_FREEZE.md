# LLM ↔ Backend Interface Specification V1.1 FREEZE

**프로젝트:** 오늘 어디 가지?  
**문서 상태:** FREEZE / 14-field contract  
**기준일:** 2026-08-28  
**대체 문서:** 이전 11-field V1.1 초안 문서는 폐기하고 본 문서를 사용한다.

## 0. Freeze 상태

TeamSpec V1.1 Intent Parser는 다음 검증을 통과한 상태로 동결한다.

- Golden 50: 50/50 exact match
- Robustness V1.1: 30/30 exact match
- JSON Schema validity: 100%
- Activity F1: 100%
- Companions F1: 100%
- Default hallucination rate: 0%

이후 필드 추가/삭제, enum 변경, 의미 변경, time-period 범위 변경은 V1.1 내부 수정이 아니라 **schema version-up**으로 처리한다.

## 1. 시스템 책임 경계

### LLM Parser 책임
- 사용자 자연어를 정확히 14개 필드의 JSON으로 구조화
- 위치 텍스트, 시간, 시간대(period), 희망 체류시간 범위, 활동, 이동수단, 동행, 예산, 공간 선호 추출
- 상대시간 해석이 필요하면 Backend가 제공한 `current_datetime`, `timezone` 사용
- 없는 정보는 `null`, `[]`, `"auto"` 기본값 유지

### Backend 책임
- 현재 GPS 좌표 확정
- `start_location_text`, `end_location_text` 지오코딩
- 지도/교통 API로 실제 이동시간 계산
- 사용자 가용 시간창과 후보별 실제 체류 가능시간 계산
- POI Feature, 혼잡도, 날씨, 이벤트 등 환경 신호 결합
- 후보 필터링/Ranking 및 최종 추천 결정

### LLM Parser가 하지 않는 일
추천지역 결정, 좌표 생성, GPS 추정, 지도 API 호출, 실제 이동시간 계산, 후보별 실제 체류 가능시간 계산, 혼잡도 계산, 날씨로 사용자 의도 변경, 최종 Ranking, 추가 질문 생성.

## 2. 호출 입력 계약

Backend는 LLM 호출 시 아래 두 종류의 입력을 전달한다.

### 2.1 User request
사용자의 원문 자연어. 전처리로 의미를 바꾸지 않는 것을 권장한다.

### 2.2 Runtime context
출력 JSON의 필드가 아니라 상대시간 해석용 호출 context다.

```json
{
  "current_datetime": "2026-08-28T17:00:00+09:00",
  "timezone": "Asia/Seoul"
}
```

- `current_datetime`: ISO-8601, timezone offset 포함
- `timezone`: IANA timezone name
- 상대시간 계산이 필요할 때만 사용
- GPS, 날씨, 혼잡도, POI feature는 Parser runtime context로 전달할 필요가 없다

## 3. 출력 JSON 계약

Parser는 **정확히 아래 14개 키를 모두 포함한 JSON object 1개**를 반환한다. 추가 키는 금지한다.

```json
{
  "start_location_text": null,
  "end_location_text": null,
  "start_time": null,
  "end_time": null,
  "start_time_period": null,
  "end_time_period": null,
  "desired_duration_min_minutes": null,
  "desired_duration_max_minutes": null,
  "activities": [],
  "transport_mode": "auto",
  "companions": [],
  "budget_max": null,
  "budget_preference": null,
  "space_preference": null
}
```

### 3.1 필드 요약

| Field | Type | Backend 의미 |
|---|---|---|
| start_location_text | string \| null | 추천 활동을 시작할 미래 위치. 현재 위치 언급만 있으면 null(GPS 우선) |
| end_location_text | string \| null | 추천 활동 이후 반드시 가야 하는 다음 목적지 |
| start_time | HH:MM \| null | 활동 시작 가능 exact time. `지금` 자체는 null |
| end_time | HH:MM \| null | 다음 일정 또는 가용 시간창의 exact end |
| start_time_period | enum \| null | exact start가 없을 때 명시된 생활 시간대 |
| end_time_period | enum \| null | exact end가 없을 때 명시된 생활 시간대 |
| desired_duration_min_minutes | int \| null | 목적지 활동에 쓰고 싶은 최소 시간(분) |
| desired_duration_max_minutes | int \| null | 목적지 활동에 쓰고 싶은 최대 시간(분) |
| activities | array | food/cafe/walk/culture/entertainment/shopping/drink |
| transport_mode | enum | auto/public_transit/walk/car |
| companions | array | solo/friend/partner/family/child/coworker |
| budget_max | int \| null | 최대 예산, 원(KRW) 단위 |
| budget_preference | enum \| null | low/medium/flexible/any |
| space_preference | enum \| null | indoor/outdoor/any. 사용자 명시 의도만 보존 |

## 4. 위치 스코프 규칙

### 4.1 현재 위치
`지금 사당인데`, `현재 홍대야`처럼 현재 위치만 말하면 `start_location_text=null`이다. Backend GPS가 source of truth다.

### 4.2 미래 시작 위치
`5시에 사당에 있을 거야`, `6시에 강남에서 일정 끝나`처럼 추천 활동이 시작될 미래 위치는 `start_location_text`에 넣는다.

### 4.3 다음 필수 목적지
`9시에 고터 가야 해`, `7시에 잠실 약속`은 `end_location_text`다. Backend는 후보에서 이 목적지까지의 이동시간을 계산해야 한다.

## 5. 시간 계약

### 5.1 exact time
- 형식: `00:00`~`23:59`
- `24:00`은 exact field에 넣지 않는다
- 같은 endpoint에 exact time과 period를 동시에 채우지 않는다
- exact time이 있으면 period는 null

### 5.2 period enum과 Backend 해석 범위

| Enum | 사용자 표현 | Backend 범위 |
|---|---|---|
| morning | 아침 | 06:00~11:00 |
| lunch | 점심 시간대 | 11:00~15:00 |
| evening | 저녁 | 18:00~24:00 |
| am | 오전 | 06:00~12:00 |
| pm | 오후 | 12:00~22:00 |

`24:00`은 evening의 **Backend 정책상 상한**일 뿐 exact-time schema 값이 아니다. Period는 서로 겹칠 수 있으며 하루를 비중첩 분할하는 enum이 아니다.

### 5.3 식사명과 period 구분
- `점심 먹고 싶어` → food, period=null
- `점심쯤 밥 먹고 싶어` → food + start_time_period=lunch

## 6. 가용 시간창과 희망 체류시간

이 둘은 완전히 다른 개념이며 동시에 존재할 수 있다.

### 6.1 Availability
사용자가 실제로 비어 있거나 사용할 수 있는 시간을 명시한 경우다.

- `지금부터 2시간 비었어` → 현재 17:00이면 end_time=19:00, duration=null/null
- `한 시간 반 정도 시간 있어` → 현재 17:00이면 end_time=18:30
- `5시부터 9시까지 시간 비어` → start_time=17:00, end_time=21:00

### 6.2 Desired duration
사용자가 추천 활동에 쓰고 싶은 시간이다.

- `2시간 놀고 싶어` → min=120, max=120
- `두세 시간` → min=120, max=180
- `한두 시간` → min=60, max=120
- `최소 2시간` → min=120, max=null
- `최대 3시간` → min=null, max=180
- `몇 시간` → null/null

**V1.1 Freeze 정책:** 실제 시간 제약이 명시되지 않은 `지금부터 두 시간 정도 뭐하지?`는 availability가 아니라 desired duration(120/120)이다.

### 6.3 동시에 존재하는 예
`5시부터 9시까지 시간 있고 2시간 놀고 싶어`

- start_time=17:00
- end_time=21:00
- desired_duration_min_minutes=120
- desired_duration_max_minutes=120

Backend는 4시간 window를 2시간 duration으로 덮어쓰면 안 된다.

## 7. 후보별 실제 체류 가능시간 - Backend 내부 계산

Parser가 `actual_available_stay_minutes` 같은 값을 만들지 않는다. 후보마다 이동시간이 다르므로 Backend가 계산한다.

권장 개념식:

```text
candidate_arrival
  = recommendation_start_reference
  + travel_time(start -> candidate)

must_leave_candidate
  = next_schedule_reference
  - travel_time(candidate -> end_location)
  - safety_buffer

actual_available_stay
  = max(0, must_leave_candidate - candidate_arrival)
```

현재 팀 정책의 safety buffer 예시는 10분이다. 이 값은 Parser contract가 아니라 Backend 정책값이다.

Backend는 `actual_available_stay`와 desired duration range를 비교해 후보 적합성을 판단한다. 예를 들어 desired min이 120분인데 후보별 실제 체류 가능시간이 75분이면 hard filter 또는 강한 penalty를 적용할 수 있다.

## 8. Activity / Transport / Companion 규칙

### 8.1 Activities
허용값만 사용한다.

- food: 밥, 맛집, 식사
- cafe: 카페, 커피
- walk: 산책, 걷기
- culture: 전시, 박물관, 미술관, 공연 관람
- entertainment: 방탈출, 보드게임, 오락실, 게임, 놀이시설
- shopping: 쇼핑
- drink: 술, 맥주, 한잔

일반적인 `놀다`, `뭐하지`, `할 거 추천해줘`는 entertainment가 아니다. 구체 활동이 없으면 `activities=[]`.

### 8.2 Transport
- 미언급: auto
- 지하철/대중교통: public_transit
- 걸어서: walk
- 차: car
- 부정된 이동수단은 선택하지 않는다

### 8.3 Companions
`companions=[]`은 solo와 다르다. solo는 사용자가 실제로 `혼자`라고 명시한 경우다.

동행 범위는 **현재 추천 활동**이다. `7시에 잠실에서 친구 만나야 해. 그 전에 밥`에서 friend는 다음 일정 사람이라 companions에 넣지 않는다.

## 9. Budget / Space 규칙

### 9.1 budget_max
구체적인 최대 금액만 원(KRW) 정수로 저장한다. 정성 표현을 숫자로 추정하지 않는다.

### 9.2 budget_preference
- low: 저렴함/가성비/지출 최소화
- medium: 적당한 가격
- flexible: 좀 비싸도 괜찮음
- any: 가격 무관

`budget_max`와 `budget_preference`는 동시에 존재할 수 있다.

### 9.3 space_preference
indoor/outdoor/any/null. 명시된 사용자 선호만 저장하며 카페=indoor, 산책=outdoor처럼 활동에서 추론하지 않는다. 날씨/혼잡도 때문에 값을 덮어쓰지 않는다.

## 10. Backend 환경 신호와 Intent 분리

다음 값은 Parser schema에 넣지 않는다.

- GPS/current coordinates
- weather
- congestion
- event signal
- POI feature
- sunrise/sunset
- candidate travel time
- candidate actual stay time

이 값들은 Ranking/환경 계층에서 별도로 유지한다. 특히 weather가 좋지 않다고 `space_preference`를 indoor로 바꾸면 안 된다.

## 11. 검증 및 오류 처리

### Contract 필수
1. LLM raw output을 JSON parse
2. `user_intent_schema_team_v1_1.json`으로 local validation
3. 14-key 계약 위반 시 Ranking 입력으로 사용하지 않음
4. 원문, runtime context, raw output, validation error를 로그로 남김

### 추가 semantic check 권장
- min/max가 둘 다 존재할 때 `min <= max`
- 같은 endpoint의 exact time + period 동시 존재 금지(현재 JSON Schema에도 금지 규칙 포함)

### API 출력 모드
V1.1 Freeze 검증은 `json_object` + local JSON Schema validation 조합으로 완료되었다. OpenAI API는 지원 모델에서 `json_schema` Structured Outputs를 권장하지만, **현재 Freeze와 동일 동작을 유지하려면 운영 이관 시 즉시 바꾸지 말고 별도 버전/회귀검증 후 전환**한다.

## 12. 검증된 호출 패턴

```python
response = client.responses.create(
    model="gpt-5.6-terra",
    instructions=prompt + "\n\n# JSON Schema\n" + schema_text,
    input=[
        {
            "role": "developer",
            "content": (
                "Runtime context for this request:\n"
                + json.dumps(runtime_context, ensure_ascii=False)
                + "\nUse it only when required to interpret relative time."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return exactly one valid JSON object only. "
                "Follow the provided JSON Schema exactly. "
                "Do not use Markdown or explanations.\n\n"
                f"User request:\n{user_input}"
            ),
        },
    ],
    text={"format": {"type": "json_object"}},
    reasoning={"effort": "none"},
    prompt_cache_key="intent-parser-team-v1-1",
    max_output_tokens=500,
)
```

중요: `json_object`를 사용할 때 input message에 JSON 출력 요구가 명시되어야 한다.

## 13. Handoff 파일

- `user_intent_schema_team_v1_1.json` - Backend validation source of truth
- `intent_parser_prompt_team_v1_1_FINAL.txt` - Freeze prompt
- `example_requests_responses_v1_1.json` - 대표 입력/출력 예시
- `backend_parser_integration_example.py` - 최소 통합 예제
- `LLM_Backend_Interface_Spec_V1_1_FREEZE.md` - 텍스트 명세
- `LLM_Backend_Interface_Spec_V1_1_FREEZE.docx` - 공유용 명세서

`.env`, API key, Golden/Robustness 내부 테스트 데이터, 평가 산출물은 Handoff에 포함하지 않는다.

## 14. 변경 관리

다음 중 하나라도 변경되면 V1.1 Freeze를 직접 수정하지 말고 새 schema version으로 관리한다.

- 14개 키 추가/삭제/이름 변경
- enum 추가/삭제
- time period 범위 변경
- availability/duration 의미 변경
- companion scope 변경
- 새로운 crowd/atmosphere/accessibility 등 intent 필드 도입

Backend와 LLM은 schema version 기준으로 함께 배포한다.
