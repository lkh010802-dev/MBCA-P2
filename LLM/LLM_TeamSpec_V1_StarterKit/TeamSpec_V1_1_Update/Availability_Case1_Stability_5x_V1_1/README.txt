Availability Case #1 Stability 5x V1.1
========================================

대상 문장:
지금부터 두 시간 정도 그냥 뭐하지?

고정 Runtime Context:
current_datetime = 2026-08-28T17:00:00+09:00
timezone = Asia/Seoul

기대값:
end_time = 19:00
desired_duration_min_minutes = null
desired_duration_max_minutes = null

목적:
같은 입력을 5번 호출해 availability 해석의 안정성을 확인합니다.

실행:
python run_test_suite_v1_1.py --input Availability_Case1_Stability_5x_V1_1\inputs.jsonl --output Availability_Case1_Stability_5x_V1_1\predictions.jsonl --overwrite

평가:
python evaluate_test_suite_v1_1.py Availability_Case1_Stability_5x_V1_1\predictions.jsonl --golden Availability_Case1_Stability_5x_V1_1\golden.jsonl --out-dir Availability_Case1_Stability_5x_V1_1\evaluation

판정 가이드:
5/5 availability -> 프롬프트 유지, 이전 실패는 변동성 가능성 큼
4/5 availability -> 대체로 안정적이나 경계 케이스로 기록
2~3/5 availability -> 프롬프트 규칙 강화 검토
0~1/5 availability -> 프롬프트 구조 수정 필요
