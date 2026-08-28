TeamSpec V1.1 Update
====================

확정 변경사항
-------------
1) 기존 desired_duration_minutes 제거
2) 아래 2개로 분리
   - desired_duration_min_minutes
   - desired_duration_max_minutes

3) 아래 2개 시간대 필드 추가
   - start_time_period
   - end_time_period

4) period 허용값
   - morning : 06:00~11:00
   - lunch   : 11:00~15:00
   - evening : 18:00~24:00
   - am      : 06:00~12:00
   - pm      : 12:00~22:00

5) Backend Runtime Context
   - current_datetime
   - timezone
   상대시간 해석이 필요할 때 LLM 호출 context로 전달

총 출력 필드: 14개

중요 의미
---------
- *_time: 정확한 HH:MM
- *_time_period: 정확한 시간이 없는 생활 시간대 enum
- 같은 endpoint의 exact time과 period는 동시에 채우지 않음
- desired duration은 사용자가 목적지에서 보내고 싶은 시간
- "시간 비었어/시간 있어"는 가용 시간창이며 desired duration이 아님
- 날씨, 이동시간, 실제 체류 가능시간, Ranking 값은 Intent Schema에 넣지 않음
- space_preference는 사용자 의도 그대로 유지

V1 Golden 50 마이그레이션 주의
-----------------------------
기존 #4:
"지금부터 두 시간 정도 그냥 뭐하지?"
V1에서는 duration=120이었으나,
V1.1에서는 가용 시간창으로 해석:
current=17:00 기준 end_time=19:00, duration min/max=null

기존 #27:
"한 시간 반 정도 시간 있어. 카페 가고 싶어"
V1에서는 duration=90이었으나,
V1.1에서는 가용 시간창:
current=17:00 기준 end_time=18:30, duration min/max=null

평가용 Runtime Context
---------------------
Golden/Test 재현성을 위해 모든 V1.1 테스트 fixture는:
current_datetime = 2026-08-28T17:00:00+09:00
timezone = Asia/Seoul

를 사용합니다.

이 값은 테스트 전용입니다.
실서비스에서는 Backend가 실제 current_datetime/timezone을 전달해야 합니다.

권장 검증 순서
-------------
1. python validate_schema_team_v1_1.py

2. Duration Unit
python run_test_suite_v1_1.py ^
  --input tests\Duration_Range_Unit_V1_1\inputs.jsonl ^
  --output tests\Duration_Range_Unit_V1_1\predictions.jsonl ^
  --overwrite

python evaluate_test_suite_v1_1.py ^
  tests\Duration_Range_Unit_V1_1\predictions.jsonl ^
  --golden tests\Duration_Range_Unit_V1_1\golden.jsonl ^
  --out-dir tests\Duration_Range_Unit_V1_1\evaluation

3. Time Period Unit
같은 방식으로 Time_Period_Unit_V1_1 실행

4. Relative Time Unit
같은 방식으로 Relative_Time_Unit_V1_1 실행

5. Location & Time Scope V1.1
같은 방식으로 Location_Time_Scope_Test_V1_1 실행

6. 전용 테스트가 안정화된 뒤에만 Golden 50 전체 회귀 실행
python run_openai_predictions_team_v1_1.py --overwrite
python evaluate_team_v1_1.py predictions_team_v1_1.jsonl

토큰 절감 원칙
-------------
- Prompt 수정마다 전체 50을 다시 돌리지 않음
- 실패한 카테고리 Unit Test만 재실행
- reasoning=none
- prompt_cache_key 사용
