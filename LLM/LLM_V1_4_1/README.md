# LLM V1.4.1 Candidate

`LLM_V1_4_FREEZE`를 보존한 채 만든 정책 보정 후보입니다.

변경 범위:

- 명시적인 `걸어서/도보로 이동`이 누락되면 `transport_mode=walk`로 보정
- 걷기 활동만 있는 경우에는 기존처럼 `transport_mode=auto` 유지
- 카페·술집·공원·산책 등 활동/장소 유형만으로 생성된 실내외 선호 제거
- 사용자가 직접 `실내/야외`를 말한 경우에만 `space_preference` 유지 또는 복구
- prompt/result cache 버전을 Candidate 전용으로 분리
- 사용자가 현재·미래의 출발 위치를 명시하면 GPS보다 `start_location_text`가 우선하도록 위치 추출 정책 수정
- 변경 전 결과가 재사용되지 않도록 prompt/result cache 버전 갱신

변경하지 않은 정책:

- 팝업의 activity 분류
- `적당`의 budget preference 분류
- 시간대 period의 백엔드 계산 방식
- 16-field schema와 모델

검증:

```powershell
python test_policy_fixes_v1_4_1.py
python run_regression_v1_4_1.py --validate-only
python run_regression_v1_4_1.py
```

- 신규 정책/경계 테스트: 11/11 PASS
- 기존 16-field 고정 데이터: 310/310 PASS
- Runtime resilience: 25/25 PASS
- 정책 정렬 중첩 문장 실제 Luna: 10/10 PASS, 160/160 fields
- 실사용·복합 문장 실제 Luna 회귀 테스트: 25/25 PASS, 400/400 fields
- 회귀 테스트 구성: `regression_cases_v1_4_1.json`
- 상세 실행 결과: `regression_report_v1_4_1.json`
