Robustness Test V1.1
======================

총 30건

카테고리:
- typo_spacing: 5
- colloquial_revision: 5
- negation: 5
- time_duration: 6
- location_scope: 4
- multi_constraint: 3
- no_overinfer: 2

고정 Runtime Context:
current_datetime = 2026-08-28T17:00:00+09:00
timezone = Asia/Seoul

권장 위치:
LLM_TeamSpec_V1_StarterKit\Robustness_Test_V1_1

TeamSpec_V1_1_Update 폴더에서 실행:

python run_test_suite_v1_1.py --input ..\Robustness_Test_V1_1\inputs.jsonl --output ..\Robustness_Test_V1_1\predictions.jsonl --overwrite

평가:

python evaluate_test_suite_v1_1.py ..\Robustness_Test_V1_1\predictions.jsonl --golden ..\Robustness_Test_V1_1\golden.jsonl --out-dir ..\Robustness_Test_V1_1\evaluation

권장 1차 Gate:
- schema_validity = 1.00
- exact_case_accuracy >= 0.90
- activity_f1 >= 0.95
- companions_f1 >= 0.95
- default_hallucination_rate < 0.02

주의:
Robustness는 Golden 50과 달리 실패가 나오는 것이 정상일 수 있습니다.
실패를 보고 즉시 프롬프트를 수정하지 말고, 실패 유형이 실제 정책 문제인지
테스트 문장의 애매함인지 먼저 분류합니다.
