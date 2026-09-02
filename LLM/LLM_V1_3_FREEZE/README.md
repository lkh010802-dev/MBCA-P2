# LLM V1.3 16-FIELD LUNA HYBRID — FREEZE

Backend의 16-field 계약(`target_location_text`, `target_location_scope` 포함)을 반영한 상용화 후보 Freeze입니다.

## 현재 구조
`사용자 입력 → GPT-5.6 Luna → Strict Structured Output(16 fields) → conservative deterministic postprocess → 최종 JSON`

- model: `gpt-5.6-luna`
- reasoning effort: `none`
- explicit prompt cache TTL: `30m`
- Strict JSON Schema
- FIX1 postprocess: 기존 FIX6 + target/scope invariant + companion scope + period endpoint 보정

## Freeze 시점 검증
- Target Location Focus 30: **30/30**
- Golden Regression 50: **50/50**
- Robustness Regression 30: **30/30**
- 합계 API regression/focus: **110/110**
- 로컬 expected 검증: 210건, schema/semantic/postprocess fixed-point 모두 PASS

상세: `docs/VALIDATION_RESULTS.md`

> 110/110은 이미 알고 있는 regression/focus set에 대한 결과입니다. 실제 일반화 성능은 `Blind100 v2` 최초 실행 점수로 별도 기록합니다.

## 핵심 파일
- `intent_parser.py`: production-oriented parser 함수
- `intent_parser_prompt_team_v1_3_COST_OPT.txt`: Freeze prompt
- `user_intent_schema_team_v1_3_STRICT.json`: 16-field Strict schema
- `intent_postprocess.py`: deterministic postprocess
- `run_eval_v1_3_hybrid.py`: API 평가 실행기
- `evaluate_v1_3.py`: exact/schema/semantic evaluator
- `FREEZE_MANIFEST.json`: Freeze core SHA-256 + 검증 기록

## 테스트
- `tests/regression/golden50`: 50
- `tests/regression/robustness30`: 30
- `tests/focus/target_location30`: 30
- `tests/expansion/blind100_migrated`: 과거 Blind100의 V1.3 migration; 신규 blind로 사용하지 않음
- `tests/blind100_v2`: **새로운 100문장 first-run blind set**

## 설치
Windows PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
`.env`에 `OPENAI_API_KEY`를 입력합니다.

## 무료 로컬 확인
```powershell
python test_postprocess_local.py
python validate_v1_3_datasets.py
python validate_blind100_v2.py
```
마지막 validator는 Freeze core hash까지 확인합니다.

## Blind100 v2 — 다음 실행
**첫 실행 전 prompt/schema/postprocess를 수정하지 마세요.**

```powershell
python run_eval_v1_3_hybrid.py --model gpt-5.6-luna --input tests/blind100_v2/inputs.jsonl --output runs/v1_3_blind100_v2_first_run.jsonl --overwrite
```

평가:
```powershell
python evaluate_v1_3.py runs/v1_3_blind100_v2_first_run.jsonl --golden tests/blind100_v2/golden.jsonl --out-dir runs/v1_3_blind100_v2_first_run_eval
```

자세한 first-run protocol은 `README_BLIND100_V2.md` 참고.

## Production 사용 예
```python
from intent_parser import parse_intent

intent = parse_intent(
    "6시에 여의도에서 끝나고 성수에서 카페 갔다가 9시에 잠실 가야 해",
    {"current_datetime":"2026-09-01T17:00:00+09:00","timezone":"Asia/Seoul"},
)
```

## Freeze 이후 변경 원칙
1. 실패 입력을 새 regression/focus case로 먼저 저장
2. 작은 focus set으로 수정 검증
3. 기존 expected 전체 로컬 fixed-point 검증
4. 마지막에 API regression을 1회 실행
5. blind first-run 점수는 수정 전 결과 그대로 보존
