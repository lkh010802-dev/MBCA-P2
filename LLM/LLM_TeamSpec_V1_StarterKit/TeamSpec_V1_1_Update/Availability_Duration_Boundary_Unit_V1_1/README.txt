Availability vs Duration Boundary Unit V1.1
============================================

목적:
- "뭐하지/뭐할까" + 시간 -> 가용 시간창
- 특정 활동 + 시간 -> 희망 체류시간
경계를 6개 문장으로 확인합니다.

고정 Runtime Context:
current_datetime = 2026-08-28T17:00:00+09:00
timezone = Asia/Seoul

프로젝트의 TeamSpec_V1_1_Update 폴더 안에 이 폴더를 복사한 뒤 실행:

python run_test_suite_v1_1.py --input Availability_Duration_Boundary_Unit_V1_1\inputs.jsonl --output Availability_Duration_Boundary_Unit_V1_1\predictions.jsonl --overwrite

python evaluate_test_suite_v1_1.py Availability_Duration_Boundary_Unit_V1_1\predictions.jsonl --golden Availability_Duration_Boundary_Unit_V1_1\golden.jsonl --out-dir Availability_Duration_Boundary_Unit_V1_1\evaluation
