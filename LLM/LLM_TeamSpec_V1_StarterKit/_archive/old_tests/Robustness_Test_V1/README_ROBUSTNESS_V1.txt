Robustness Test V1
==================

목적
----
기존 Golden 50이 기본 기능 회귀 테스트라면,
Robustness V1은 실제 사용자가 입력할 법한 지저분한 문장에서도
TeamSpec V1의 11개 JSON 계약을 안정적으로 지키는지 확인합니다.

총 25개 / 9개 카테고리
---------------------
- colloquial: 구어체/축약어 3
- typo: 오타/비표준 표기 3
- self_correction: 말바꾸기/최종 의도 3
- complex: 여러 조건 혼합 3
- negation: 부정/제외 표현 3
- ambiguous_time: 모호한 시간 3
- schedule_scope: 현재 활동과 다음 일정 구분 3
- space_boundary: 실내/야외 경계 2
- noise_or_sparse: 잡음/정보 부족 2

중요 원칙
---------
- 기존 Schema나 Prompt를 수정하지 않습니다.
- 날짜는 현재 계약에 없으므로 "내일" 자체는 JSON에 저장되지 않습니다.
- 정확하지 않은 시간 표현("저녁쯤", "두세시간")은 임의 숫자로 만들지 않습니다.
- 말바꾸기는 마지막으로 확정된 의도를 정답으로 둡니다.
- 부정된 활동/이동수단은 positive signal로 넣지 않습니다.
- 현재 활동의 동행인과 다음 일정에서 만나는 사람을 구분합니다.

1) Golden 자체 검증
-------------------
python validate_robustness_v1.py

기대:
Golden cases: 25
Schema valid: 25/25
PASS ...

2) 처음에는 5개만 API 실행
-------------------------
python run_robustness_v1.py --limit 5 --overwrite

predictions_robustness_v1.jsonl 확인 후 이상 없으면 전체 실행.

3) 전체 25개 실행
----------------
python run_robustness_v1.py --overwrite

기본:
- model = gpt-5.6-terra
- reasoning = none
- prompt_cache_key 사용
- max_output_tokens = 500

4) 평가
-------
python evaluate_robustness_v1.py predictions_robustness_v1.jsonl --golden golden_tests_robustness_v1.jsonl --schema user_intent_schema_team_v1.json --out-dir evaluation_result_robustness_v1

결과:
evaluation_result_robustness_v1/
- evaluation_summary.json
- evaluation_cases.csv
- evaluation_report.html

함께 생성:
- robustness_v1_usage_summary.json

초기 Gate
---------
Schema Validity >= 100%
Exact Case Accuracy >= 88%
Activity F1 >= 95%
Companions F1 >= 95%
Default Hallucination Rate < 3%
각 Category Accuracy >= 67%는 탐색용 참고선

주의
----
이 Gate는 서비스 SLA가 아니라 Robustness V1의 초기 개발 기준입니다.
첫 실행 결과를 본 뒤 실패 유형을 분석하여 V1.1 Test 또는 Prompt 개선 여부를 결정합니다.
