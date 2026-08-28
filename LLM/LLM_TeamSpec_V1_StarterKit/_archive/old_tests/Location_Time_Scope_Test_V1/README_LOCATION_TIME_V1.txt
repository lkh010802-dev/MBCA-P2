Location & Time Scope Test V1
=============================

목적
----
현재 TeamSpec V1 계약을 변경하지 않고,
위치/시간 정보가 문장 안에서 어떤 역할을 하는지 LLM이 안정적으로 구분하는지 검증합니다.

중요:
- 범위형 desired_duration_minutes 문제는 이번 테스트 범위에서 제외합니다.
- Prompt / Schema는 상위 LLM_TeamSpec_V1_StarterKit 폴더의 최신 파일을 사용합니다.
- .env 역시 상위 폴더에서 읽습니다.

권장 폴더 구조
--------------
LLM_TeamSpec_V1_StarterKit/
├─ .env
├─ intent_parser_prompt_team_v1.txt
├─ user_intent_schema_team_v1.json
└─ Location_Time_Scope_Test_V1/
   ├─ run_location_time_v1.py
   ├─ evaluate_location_time_v1.py
   ├─ validate_location_time_v1.py
   ├─ eval_inputs_location_time_v1.jsonl
   └─ golden_tests_location_time_v1.jsonl

총 24개 / 6개 카테고리
----------------------
1. current_location_gps (4)
   현재 위치("지금/현재")는 GPS가 담당하므로 start_location_text=null인지 확인

2. future_start (4)
   미래 출발 장소/시각이 start_location_text/start_time으로 들어가는지 확인

3. mandatory_destination (4)
   다음 필수 목적지와 도착 시각이 end_location_text/end_time으로 들어가는지 확인

4. schedule_end_as_start (4)
   "6시에 강남에서 일정 끝나고"가 추천 활동의 시작점으로 해석되는지 확인

5. mixed_timeline (4)
   현재 위치 + 미래 시작점 + 다음 목적지가 한 문장에 섞여 있을 때 scope 구분

6. time_window_boundary (4)
   "지금부터", "7시부터 9시까지" 등 시간창 해석과 duration 자동 계산 금지 확인

실행
----

1) Golden 정답 Schema 검증 (API 호출 없음)
프로젝트 루트에서:

python Location_Time_Scope_Test_V1\validate_location_time_v1.py

기대:
Golden cases: 24
Schema valid: 24/24
PASS ...

2) API 5개만 파일럿
python Location_Time_Scope_Test_V1\run_location_time_v1.py --limit 5 --overwrite

정상적으로 -> OK가 나오면 전체 실행.

3) 전체 24개
python Location_Time_Scope_Test_V1\run_location_time_v1.py --overwrite

생성:
Location_Time_Scope_Test_V1/
- predictions_location_time_v1.jsonl
- location_time_v1_usage_summary.json

4) 평가
python Location_Time_Scope_Test_V1\evaluate_location_time_v1.py Location_Time_Scope_Test_V1\predictions_location_time_v1.jsonl

생성:
Location_Time_Scope_Test_V1/evaluation_result_location_time_v1/
- evaluation_summary.json
- evaluation_cases.csv
- evaluation_report.html

초기 Gate
---------
Schema validity >= 100%
Exact case accuracy >= 88%
start_location_text >= 95%
end_location_text >= 95%
start_time >= 95%
end_time >= 95%
Activity F1 >= 95%
Companions F1 >= 95%

주의
----
이 Gate는 서비스 SLA가 아니라 개발 초기 판단 기준입니다.
실패가 발생하면 전체 24개를 반복 실행하지 말고,
실패 유형만 별도 Unit Test로 분리해 수정 여부를 판단합니다.
