LLM Backend Handoff V1.1 FREEZE
================================

이 폴더는 TeamSpec V1.1 Intent Parser의 Backend 전달용 최소 패키지입니다.

FREEZE 상태
- Golden 50: 50/50
- Robustness V1.1: 30/30
- Schema validity: 100%
- Exact accuracy: 100%

공식 파일
1. user_intent_schema_team_v1_1.json
2. intent_parser_prompt_team_v1_1_FINAL.txt
3. LLM_Backend_Interface_Spec_V1_1_FREEZE.docx
4. LLM_Backend_Interface_Spec_V1_1_FREEZE.md
5. example_requests_responses_v1_1.json
6. backend_parser_integration_example.py

주의
- 이전 11-field V1.1 interface 문서는 폐기합니다.
- 현재 계약은 14-field V1.1 FREEZE입니다.
- .env/API key/내부 Golden/Robustness 평가 데이터는 포함하지 않습니다.
- 필드/enum/의미 변경은 V1.1을 덮어쓰지 말고 version-up합니다.
