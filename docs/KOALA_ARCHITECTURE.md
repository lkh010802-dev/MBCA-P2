KOALA 백엔드 · DB 통합 구조 명세

기준 버전: KOALA 1.1
기준일: 2026-09-21
현재 상태: Backend · DB · ML 서비스 통합 및 검증 완료 / KOALA 1.1 Code Freeze
다음 단계: AWS 배포 및 운영환경 구성

1. KOALA는 어떤 서비스인가?

KOALA는 사용자의 현재 위치, 사용 가능한 시간, 다음 일정, 원하는 활동 등을 바탕으로 지금 방문하기 적합한 서울 지역을 추천하고, 해당 지역의 실제 장소와 방문 코스까지 만들어주는 서비스다.

예를 들어 사용자가 다음과 같이 요청했다고 가정한다.

“지금 사당인데 3시간 정도 시간이 있어. 카페도 가고 산책도 하고 싶어.”

KOALA는 단순히 주변 카페를 검색해서 보여주는 것이 아니다.

사용자의 요청을 분석한 뒤 다음 과정을 거친다.

사용자 자연어 요청

↓

현재 위치 · 시간 · 활동 조건 파악

↓

방문 가능한 지역 후보 탐색

↓

카페·산책하기 좋은 지역인지 평가

↓

실제 이동 가능한 지역인지 평가

↓

방문 예상시간의 혼잡도 확인 또는 ML 예측

↓

종합점수 계산

↓

추천 지역 선정

↓

추천 지역의 실제 장소 검색

↓

사용자가 방문 장소 선택

↓

실제 이동시간 계산

↓

방문순서 최적화

↓

주어진 시간 안에 방문 가능한지 최종 판정

따라서 KOALA의 핵심 구조는 다음과 같다.

지역 추천 → 실제 장소 추천 → 코스 생성



2. KOALA 전체 흐름

전체 서비스는 크게 네 단계로 나눌 수 있다.

STEP 1. 사용자 요청 이해

사용자 자연어 + GPS

↓

LLM / 입력 조건 처리

↓

추천에 필요한 구조화된 조건 생성

STEP 2. 방문할 지역 추천

서울 공식 121 POI

서울 421 행정동 후보

↓

활동 적합도 평가

↓

이동 가능성 평가

↓

혼잡도 평가

↓

Final Score

↓

추천지역 Ranking

STEP 3. 실제 장소 추천

추천지역

↓

Kakao / TourAPI / Popup 등의 실제 장소 데이터

↓

사용자가 방문할 장소 선택

STEP 4. 실제 코스 생성

선택 장소

↓

실제 이동시간 계산

↓

방문순서 최적화

↓

필요시간 계산

↓

FEASIBLE / INFEASIBLE



3. 각 시스템은 무엇을 담당하는가?
구성요소	역할
Frontend	사용자 입력 및 추천 결과 표시
LLM / 입력 처리	자연어를 추천 조건으로 구조화
FastAPI Backend	후보 생성, 이동시간, 점수 계산, Ranking, 장소·코스 생성
혼잡도 예측 ML	생활인구 기반 미래 혼잡도 예측
서울 Citydata	공식 121 POI의 혼잡도 제공
서울 생활인구	혼잡도 ML의 주요 입력 데이터
Kakao	위치, 실제 장소 및 이동 관련 기능
TourAPI	문화·관광 장소 정보 보조
Popup 데이터	팝업스토어 등의 장소 정보
MySQL	회원·인증·사용자 선호 저장

여기서 중요한 점은 Backend와 ML의 역할이 서로 다르다는 것이다.

ML은 혼잡도를 예측한다.

Backend는 ML 결과를 다른 추천 요소와 결합하여 최종 지역을 결정하고 실제 장소와 코스까지 연결한다.



4. 왜 지역 후보가 121 + 421인가?

KOALA 초기 지역 후보의 기반은 서울시에서 제공하는 주요 장소 121 POI(Point of Interest) 다.

121 POI는 서울 Citydata를 통해 혼잡도 정보를 받을 수 있다는 장점이 있다.

하지만 121개 지역만으로 서울 전체를 충분히 커버하기에는 한계가 있다.

사용자 주변에 방문하기 좋은 지역이 있어도 공식 121 POI에 포함되어 있지 않으면 추천 후보가 될 수 없기 때문이다.

이를 보완하기 위해 서울의 행정동을 추가 후보로 확장했다.

현재 KOALA의 지역 후보는:

서울 공식 121 POI

421 행정동

으로 구성된다.



5. 121 POI와 421 행정동의 차이
구분	공식 121 POI	421 행정동
후보 Source	poi121	local_resd
지역 기준	서울 주요 장소	행정동
활동 적합도	상권 데이터 기반	행정동 상권 데이터 기반
혼잡도	서울 Citydata	생활인구 기반 혼잡도 예측 ML
현재 ML 적용	없음	D-4 Direct LightGBM
ML 실패 시	해당 없음	중립점수 3.0
최종 Ranking	Backend	Backend

Backend에서는 두 후보를:

candidate_source = poi121

candidate_source = local_resd

로 구분한다.



6. 428 / 427 / 421은 왜 다른가?

ML과 Backend 데이터를 보다 보면 세 가지 숫자가 등장한다.

숫자	의미
428	ML 모델이 가진 행정동 Category
427	서비스 Support Master Allowlist
421	실제 좌표까지 확인되어 추천 후보로 사용하는 행정동

서로 다른 기준의 숫자이기 때문에 동일할 필요가 없다.

현재 실제 KOALA 비121 지역 추천에는 421개 행정동이 사용된다.



7. 421개 지역을 전부 계산하지 않는 이유

421개 모든 행정동에 대해 실제 이동시간과 ML 추론을 실행하면 불필요한 계산과 외부 API 호출이 크게 증가한다.

따라서 먼저 저비용 계산으로 후보를 줄인다.

421 행정동

↓

거리 / 우회거리 기준 약 Top 20

↓

사용자가 원하는 활동을 지원하는 지역 우선

↓

후보가 부족하면 가까운 지역으로 보충

↓

최대 약 5개 후보

↓

실제 이동시간 계산

↓

혼잡도 ML 추론

↓

Final Score 계산

즉 빠른 계산으로 후보를 먼저 줄이고, 비용이 큰 실제 계산은 소수 후보에만 수행한다.



8. 지역 추천 점수는 어떻게 만들어지는가?

지역을 평가하는 핵심 요소는 세 가지다.

Activity Score

사용자가 원하는 활동을 하기 얼마나 좋은 지역인지 평가한다.

대표 활동은:

음식
카페
산책
문화
오락
쇼핑
술

등이다.

상권 데이터를 이용해 지역별 활동 적합도를 계산한다.

Travel Score

사용자의 현재 위치와 일정 등을 기준으로 해당 지역까지 이동하는 부담을 평가한다.

실제 이동시간이 짧을수록 높은 점수를 받는다.

Congestion Score

방문 예상시간의 혼잡도를 평가한다.

121 POI:

서울 Citydata

421 행정동:

생활인구 기반 혼잡도 예측 ML

을 사용한다.



9. Final Score

활동 조건이 있는 경우:

Final Score

= Activity Score × 0.5

Travel Score × 0.3
Congestion Score × 0.2

즉:

활동 50% + 이동 30% + 혼잡도 20%

다.

활동 조건이 없는 경우:

Final Score

= Travel Score × 0.6

Congestion Score × 0.4

를 사용한다.

따라서 혼잡도 ML 하나가 최종 추천을 결정하는 것이 아니다.

ML은 추천을 구성하는 하나의 중요한 입력을 담당한다.



10. KOALA의 혼잡도 ML은 어떻게 시작됐는가?

KOALA에서는 지역 추천 시 현재 거리뿐만 아니라:

“사용자가 실제로 그 지역에 도착했을 때 얼마나 혼잡할 것인가?”

도 고려하고자 했다.

이를 위해 ML 담당에서는 서울 생활인구 데이터를 활용한 미래 혼잡도 예측 모델을 개발했다.

단순히 생활인구 숫자를 그대로 사용하는 것이 아니라:

지역 정보

요일 / 시간 정보

과거 생활인구

Lag Feature

Rolling / 변화량 등의 Feature

를 구성하여 미래의 상대적인 혼잡 상태를 예측하는 구조를 만들었다.

이 과정에서 LightGBM 기반 모델을 포함한 머신러닝 모델을 개발하고 성능을 검증했다.

즉 현재의 D-4 모델부터 KOALA ML이 시작된 것이 아니다.



11. 기존 LightGBM 모델이 만든 기반

기존 ML 연구를 통해 다음과 같은 핵심 구조가 만들어졌다.

생활인구 데이터 구조

↓

행정동 기반 학습 구조

↓

시간 Feature

↓

Lag / Rolling / 변화량 Feature

↓

상대 생활인구 기반 Target

↓

LightGBM 모델링

↓

미래 혼잡도 예측

즉:

어떤 데이터를 사용할 것인지

어떤 Feature를 만들 것인지

혼잡도를 어떻게 정의할 것인지

행정동별 미래 혼잡도를 어떻게 예측할 것인지

에 대한 기반이 기존 ML 연구에서 만들어졌다.

현재 서비스 모델 역시 이 작업과 단절되어 있지 않다.



12. 기존 ML 모델을 그대로 서비스에 넣을 수 없었던 이유

모델 자체보다 먼저 해결해야 할 데이터 가용성 문제가 있었다.

연구환경에서는 과거 데이터셋을 이용해 필요한 시계열을 구성할 수 있다.

하지만 실제 KOALA 서비스에서는 사용자가 요청한 현재 시점 직전까지의 생활인구가 항상 준비되어 있는 것이 아니다.

예를 들어:

사용자가 오늘 오후 3시에 추천을 요청했다고 해서

오늘 오후 2시의 생활인구까지 즉시 확보되어 있다고 보장할 수 없다.

서울 생활인구 데이터에는 실제 제공 시차가 존재하기 때문이다.

따라서 연구환경에서 가능했던:

“현재 시점 직전까지 생활인구가 모두 존재한다.”

라는 조건을 실제 서비스에서 그대로 가정할 수 없었다.



13. 기존 ML을 그대로 사용하기 위한 방법도 검토했다

기존 시계열 기반 구조를 그대로 활용하기 위해 최근 부족한 생활인구 구간을 과거 Profile 등으로 복원하는 방법도 검토했다.

구조는 다음과 같다.

실제로 확보 가능한 생활인구

↓

부족한 최근 구간 추정

↓

최근 시계열 복원

↓

기존 Feature 재생성

↓

기존 모델 입력

하지만 검증 과정에서 기존 Profile과 실제 서비스 데이터 사이의 시간축 및 공간축 정합성 문제가 확인됐다.

또한 추정값으로 최근 시계열을 복원할 경우:

변화량

Rolling Std

단기 변동성

등의 Feature 분포가 실제 관측 데이터와 달라질 가능성도 있었다.

따라서 단순히 없는 데이터를 만들어 기존 모델에 넣는 방식을 최종 서비스 구조로 채택하지 않았다.

이것은 기존 ML 모델의 성능 문제라기보다 실제 운영환경에서 입력 데이터를 안정적으로 공급할 수 있느냐의 문제였다.



14. D-4 Direct로 전환한 이유

여기서 접근 방식을 변경했다.

핵심 아이디어는:

없는 최신 데이터를 추정해서 모델에 넣지 말고, 실제 서비스에서 확실하게 확보할 수 있는 과거 데이터만 사용해서 미래 혼잡도를 직접 예측하자.

였다.

이 원칙을 적용한 서비스용 모델이 D-4 Direct다.



15. 기존 LightGBM과 D-4 Direct의 관계

이 부분이 KOALA ML 구조에서 가장 중요하다.

D-4 Direct는:

기존 LightGBM 모델을 버리고 전혀 다른 모델을 새로 만든 것

이 아니다.

전체 발전과정은 다음과 같다.

생활인구 기반 혼잡도 예측 문제 정의

↓

Feature Engineering

↓

LightGBM 기반 혼잡도 예측 모델 개발

↓

모델 성능 검증

↓

실제 KOALA 서비스 적용 검토

↓

생활인구 데이터 제공 시차 문제 발견

↓

최근 시계열 복원 방식 검토

↓

정합성 및 운영 안정성 문제 확인

↓

실제 확보 가능한 D-4 데이터를 기준으로 Direct Prediction 구조 설계

↓

기존 ML의 Feature / Target / 지역 구조 / LightGBM 모델링 방식 활용

↓

D-4 Direct LightGBM

↓

KOALA 서비스 적용

따라서 D-4 Direct는 기존 ML 연구 결과를 실제 서비스 환경에 맞게 발전시킨 서비스 적용 모델이라고 이해하는 것이 정확하다.



16. 기존 ML 자산이 D-4에 어떻게 활용됐는가?
기존 ML 자산	D-4 Direct에서의 활용
생활인구 데이터 구조	핵심 입력 데이터로 활용
행정동 기반 모델링	동일한 지역 단위 기반
시간 Feature	서비스용 Feature 구성에 활용
Lag Feature	실제 확보 가능한 과거 시점 기준으로 구성
상대 생활인구 Target	혼잡 Class 정의에 활용
LightGBM 모델링	D-4 Direct 예측 모델에 활용
기존 실험 결과	서비스 모델 설계·비교 기준으로 활용

따라서 D-4는 기존 ML과 별개의 작업이 아니라 기존 ML 개발 결과 위에서 만들어진 서비스 적용 단계다.



17. 왜 D-4라고 부르는가?

실제 서비스에서 안정적으로 확보할 수 있는 과거 생활인구를 기준으로 모델 입력을 구성한다.

대표적으로:

T-96

T-168

T-336

시점의 데이터를 사용한다.

T-96은 96시간 전, 즉 약 4일 전이다.

그래서 서비스 적용 구조를 D-4 Direct라고 부른다.

중요한 것은 단순히 “4일 전 데이터만 본다”는 의미가 아니다.

실제 운영환경에서 확보 가능한 과거 데이터를 기준으로 미래 혼잡도를 직접 예측한다는 것이 핵심이다.



18. D-4 Direct도 LightGBM 기반 모델이다

현재 KOALA 서비스에서 사용하는 D-4 Direct는 기존 LightGBM 기반 혼잡도 예측 연구를 대체하는 단순 Backend 로직이 아니다.

기존 ML의 구조를 실제 데이터 가용 조건에 맞게 재구성한 LightGBM 기반 서비스 모델이다.

예측 Horizon별로:

d4_direct_h1.joblib

d4_direct_h2.joblib

d4_direct_h3.joblib

d4_direct_h4.joblib

d4_direct_h5.joblib

d4_direct_h6.joblib

을 사용한다.

즉 후보지역의 예상 도착시간에 따라 +1시간 ~ +6시간 모델 중 적절한 Artifact를 선택하여 추론한다.



19. ML과 Backend의 역할 구분

이 부분은 팀 역할 관점에서도 명확하게 구분할 필요가 있다.

ML 담당 — 혼잡도 예측 모델 개발

생활인구 데이터 분석

↓

Feature Engineering

↓

LightGBM 기반 모델 개발

↓

Target / Class 설계

↓

모델 실험 및 성능 검증

↓

실제 서비스 데이터 조건 반영

↓

D-4 Direct 모델

↓

+1h ~ +6h Model Artifact

Backend 담당 — 모델의 실제 서비스 통합

ML Artifact 수용

↓

KOALA Runtime에 Artifact 포함

↓

서울 생활인구 API 연동

↓

Population History 관리

↓

421 행정동 후보 ↔ ML 입력 연결

↓

후보 예상 도착시간 계산

↓

적절한 Horizon 모델 선택

↓

실제 ML 추론

↓

ML 출력 → Congestion Score 변환

↓

Activity / Travel과 결합

↓

Final Score

↓

지역 Ranking

즉 ML 담당이 예측 모델을 만들고, Backend 담당이 그 모델을 실제 KOALA 서비스에서 사용할 수 있도록 연결한다.

둘 중 어느 하나가 다른 하나를 대체하는 관계가 아니다.



20. D-4 모델의 입력

대표 입력은 다음과 같다.

입력	의미
LOCAL_RESD	행정동 식별
issue_time	예측 기준시각
Population History	과거 생활인구
T-96	96시간 전
T-168	168시간 전
T-336	336시간 전

후보지역 예상 도착시간에 따라:

+1h
+2h
+3h
+4h
+5h
+6h

중 적절한 모델을 선택한다.



21. 서비스용 ML Artifact

실제 서비스에서 사용하는 Artifact는 KOALA 저장소 내부:

ml/d4_direct/

에 포함되어 있다.

주요 Artifact:

d4_direct_h1.joblib
d4_direct_h2.joblib
d4_direct_h3.joblib
d4_direct_h4.joblib
d4_direct_h5.joblib
d4_direct_h6.joblib

그리고 Metadata, Provider, Support Master 등 서비스 추론에 필요한 파일들이 함께 존재한다.

따라서 실제 배포되는 KOALA는 개발자의 별도 ML 작업 폴더에 의존하지 않는다.

별도 ML 환경은 연구·실험·재학습·재현 영역이고,

KOALA 저장소 내부 Artifact는 서비스 추론 영역이다.



22. ML은 무엇을 예측하는가?

현재 ML은 서울 Citydata의 공식 혼잡도 등급 자체를 예측하는 것이 아니다.

예측하려는 것은:

해당 행정동의 생활인구가 평소 같은 조건에 비해 상대적으로 어느 수준인가

이다.

현재 Class는 다음과 같다.

Class	기준
p0	ratio ≤ 0.80
p1	0.80 < ratio ≤ 1.20
p2	1.20 < ratio ≤ 1.50
p3	ratio > 1.50

모델은 각 Class일 확률:

p0 / p1 / p2 / p3

을 반환한다.



23. ML 결과를 Backend가 어떻게 사용하는가?

ML 확률을 그대로 Final Score에 넣지 않는다.

Backend가 추천용 혼잡도 점수로 변환한다.

Congestion Score

= 5 × p0 + 4 × p1 + 2 × p2 + 1 × p3

상대적으로 한산할 가능성이 높을수록 높은 점수를 받는다.

즉:

ML

p0 / p1 / p2 / p3

↓

Backend

congestion_score

↓

Activity + Travel + Congestion

↓

final_score

↓

Ranking

구조다.



24. ML 추론이 실패하면 어떻게 되는가?

ML 장애 하나 때문에 전체 추천을 실패시키지 않는다.

대표 상태는:

Status	의미
ok	정상 추론
unsupported_region	지원하지 않는 지역
insufficient_history	필요한 과거 데이터 부족
population_source_failure	생활인구 공급 실패
inference_failure	모델 추론 실패

정상 추론이면 ML 결과를 사용한다.

실패하면:

Congestion Score = 3.0

중립값을 적용하고 해당 후보를 유지한다.

또한 421 후보의 ML이 실패했다고 해서 121용 Citydata를 대신 사용하지 않는다.



25. 생활인구 History

D-4 추론에는 과거 생활인구가 필요하다.

서울 생활인구 Open API에서 데이터를 수집한다.

하루 정상 데이터:

427 행정동 × 24시간 = 10,248 rows

현재 서비스에서 유지하는 History Window:

11일

정상 Bootstrap 결과:

112,728 rows

Fresh Clone에서도 빈 상태에서 11일 데이터를 수집해 112,728행을 만드는 것까지 검증했다.



26. 생활인구 자동 유지보수

population_history_maintenance.py

가 필요한 생활인구 History를 유지한다.

현재 날짜 확인

↓

사용 가능한 최신 날짜 계산

↓

필요한 11일 범위 확인

↓

기존 보유 날짜 확인

↓

누락된 날짜만 서울 API에서 수집

↓

History 갱신

특정 날짜의 서울 API 데이터가 아직 제공되지 않으면 나머지 날짜 수집은 계속하고, 실패한 날짜는 다음 실행에서 다시 시도한다.



27. 생활인구 게시 시차와 D-4 운영 정책

D-4 Direct는 실제 서비스에서 확보 가능한 과거 생활인구를 사용하지만, D-4 날짜의 생활인구 데이터 역시 하루 중 즉시 제공되는 것은 아니다.

현재 개발 과정에서 확인한 패턴에서는 새로운 D-4 생활인구 데이터가 대체로 14:20~14:30 KST 전후에 확인되고 있다.

단, 이는 개발 과정에서 관찰한 게시 패턴이며 서울시가 보장한 공식 게시시각으로 간주하지 않는다.

따라서 당일 새로운 D-4 데이터가 아직 게시되지 않은 시간에는 ML이 요구하는 최신 Population History가 부족할 수 있다.

이 경우 KOALA는 전체 추천을 실패시키지 않는다.

D-4 History 부족

↓

insufficient_history

↓

congestion_score = 3.0

↓

421 행정동 후보 유지

↓

Activity Score / Travel Score와 함께 Final Score 계산

↓

추천 서비스 계속 진행

즉 데이터 게시 전에는 일부 421 후보에서 ML 기반 혼잡도 차별화가 일시적으로 약해질 수 있지만, 지역 추천 → 실제 장소 추천 → 코스 생성 전체 서비스는 계속 동작한다.

새로운 D-4 데이터가 게시된 이후 population_history_maintenance.py가 실행되면 누락된 날짜를 수집한다.

D-4 데이터 게시

↓

Population Maintenance 실행

↓

누락 날짜 확인

↓

생활인구 수집

↓

History 갱신

↓

이후 요청부터 정상 ML 추론

따라서 이는 서비스 장애가 아니라 데이터 게시 시차 동안 ML 혼잡도만 중립값으로 Graceful Degradation하는 구조다.

AWS 운영 시

AWS에서는 현재 관찰된 데이터 게시 패턴을 고려해 Population Maintenance를 15:00 KST 이후 실행하도록 구성하는 것을 우선 검토한다.

게시가 평소보다 늦어지는 경우를 대비해 추가 재시도 스케줄도 구성할 수 있다.

예:

15:00

↓

16:00

↓

17:00

Maintenance는 이미 확보된 날짜를 다시 수집하는 것이 아니라 누락된 날짜를 확인하여 보완하도록 구성되어 있으므로 반복 실행에 적합하다.

실제 AWS 운영 스케줄은 배포 시점까지 게시 패턴을 추가 확인한 뒤 확정한다.

D-5로 임의 변경하지 않는 이유

데이터 게시 시차를 피하기 위해 현재 D-4 모델에 단순히 D-5 데이터를 입력하는 방식은 사용하지 않는다.

현재 D-4 Direct는 T-96, T-168, T-336 등 정해진 시차의 Feature를 기준으로 학습·검증된 모델이다.

따라서 D-4 대신 임의로 D-5 데이터를 사용하면 학습 당시와 실제 추론 시점의 Feature 의미가 달라진다.

D-5 구조가 필요하다면 별도의 Feature 구성, 모델 재학습, 성능 비교 및 서비스 검증이 필요하다.

현재 KOALA 1.1에서는 D-4 모델을 유지하고 데이터 게시 전에는 기존 중립값 Fallback을 사용하는 정책을 유지한다.



28. 시간 처리

생활인구는 시간 단위 데이터이므로 ML 기준시각을 정시로 맞춘다.

예:

15:28

↓

15:00

또한 서울 생활인구 기준이므로 서울 현지시간을 유지한다.

예:

15:28 +09:00

↓

서울 현지시각 15:28 유지

↓

Timezone 정보 제거

↓

15:00

Population Loader와 ML Provider는 동일한 model_issue_time을 사용한다.



29. 실제 Final Score 검증 예시

낙성대동 실제 검증에서:

항목	값
Activity Score	5
Travel Score	3.6
ML 기반 Congestion Score	약 3.9836

따라서:

5 × 0.5 + 3.6 × 0.3 + 3.9836 × 0.2

≈ 4.3767

실제 /recommend 응답의 final_score와 일치했다.

즉:

ML 추론

↓

Backend 점수 변환

↓

Activity / Travel 결합

↓

Final Score

↓

Ranking

까지 실제 서비스에 연결되어 있다.



30. 지역 추천 이후에는 어떻게 되는가?

ML의 핵심 역할은 지역 추천 단계다.

지역이 결정된 이후에는 실제 장소를 중심으로 기존 Backend 흐름이 이어진다.

/recommend

↓

추천지역

↓

/recommend/places

↓

실제 장소 검색

↓

사용자 장소 선택

↓

선택 사전검증

↓

/recommend/course

↓

실제 이동시간

↓

방문순서 최적화

↓

FEASIBLE / INFEASIBLE

즉 421 행정동과 ML을 추가했다고 장소·코스 시스템을 전부 새로 만든 것이 아니다.

기존 KOALA 파이프라인에 새로운 지역 후보와 ML 기반 혼잡도 공급원을 연결한 구조다.



31. 실제 전체 E2E 검증

실제 다음과 같은 요청으로 전체 흐름을 검증했다.

“지금부터 3시간 정도 시간이 있는데 카페도 가고 산책도 하고 싶어.”

자연어 요청

↓

GPS

↓

현재 지역 사당역

↓

121 + 421 후보 평가

↓

비121 추천지역 낙성대동

↓

ML 혼잡도 추론

↓

Final Ranking

↓

Kakao 실제 장소 6개

↓

카페 + 산책 장소 선택

↓

선택 사전검증

↓

실제 이동시간 계산

↓

코스 생성

결과:

항목	결과
체류시간	120분
실제 이동시간	26분
총 필요시간	146분
사용 가능시간	180분
잔여시간	34분
최종 판정	FEASIBLE

따라서:

자연어 → 지역 → ML → Ranking → 실제 장소 → 이동 → 코스

전체 서비스 연결을 확인했다.



32. 회원과 DB는 왜 필요한가?

KOALA에는 추천 기능 외에도 사용자 계정과 개인화를 위한 DB가 존재한다.

회원가입 정보는:

users

에 저장된다.

사용자가:

“실내를 선호한다.”

“대중교통을 선호한다.”

“카페를 매우 좋아한다.”

같은 선호를 설정하면 사용자 선호 DB에 저장한다.

향후 추천 개인화에 활용할 수 있는 구조다.



33. DB 관계 — 쉽게 보는 ERD

users

├── 1 : 1 → user_preferences

└── 1 : N → user_activity_preferences

　　　　　　　　　　　↓

　　　　　　　　　N : 1

　　　　　　　　　　　↓

　　　　　　activity_categories

각 테이블의 역할은 다음과 같다.

Table	역할
users	사용자 계정
user_preferences	공간 / 이동수단 등 공통 선호
activity_categories	활동 종류 Master
user_activity_preferences	사용자별 활동 선호도

기본 Activity Category는:

food
cafe
walk
culture
entertainment
shopping
drink

총 7개다.



34. 인증 / 사용자 선호 API
API	역할
POST /auth/signup	회원가입
POST /auth/login	로그인 / JWT 발급
GET /users/me	현재 사용자 조회
GET /users/me/preferences	사용자 선호 조회
PUT /users/me/preferences	사용자 선호 저장 / 수정

실제 Docker MySQL에서:

회원가입

↓

로그인

↓

JWT

↓

현재 사용자 조회

↓

Preferences 저장

↓

Preferences 조회

↓

MySQL 직접 확인

전체 과정을 E2E 검증했다.



35. DB 생성 및 재현

개발환경은:

Docker Compose

↓

MySQL 8.4

↓

koala_db

↓

Alembic Migration

↓

Activity Category Seed

↓

FastAPI

구조다.

현재 Migration 기준:

20260916_0001

새로운 DB에서는:

DATABASE_URL 설정

↓

alembic upgrade head

↓

python -m scripts.seed_activity_categories

↓

FastAPI 실행

순서로 재구성할 수 있다.

Fresh Clone + 빈 MySQL 환경에서도 실제 재현을 완료했다.



36. 외부 API / 데이터
데이터 / 서비스	역할
서울 Citydata	공식 121 POI 혼잡도
서울 생활인구	ML 입력 History
Kakao	위치 / 장소 / 이동 관련 기능
TourAPI	문화·관광 장소 정보 보조
Popup 데이터	팝업스토어 등 별도 장소 정보
MySQL	회원 / 인증 / 사용자 선호
LightGBM Artifact	421 행정동 미래 상대 생활인구 예측


37. Popup 데이터 — 현재 구조

Popup 정보는 계속 변경되므로 정기적으로 갱신해야 한다.

AWS 서버의 정기 Scheduler가 `download_popup_json.py`를 실행해 KST 날짜 기준
`popup_data/YYYYMMDD_popup_places.json`을 생성하거나 같은 날짜 파일을 원자적으로 교체한다.
다운로드 응답은 JSON 형식, 비어 있지 않은 목록, 최소 한 건 이상의 정상화 가능 레코드를
확인한 뒤에만 저장하므로 실패한 다운로드가 기존 날짜 파일을 훼손하지 않는다.

FastAPI는 요청 시점의 KST 기준으로 다음 순서로 파일을 선택한다.

- 08:40 이전: 전날 `YYYYMMDD_popup_places.json` → `data/popup_places_fallback.json`
- 08:40 이후: 당일 `YYYYMMDD_popup_places.json` → 전날 파일 → `data/popup_places_fallback.json`

`data/popup_places_fallback.json`은 날짜별 운영 파일을 읽을 수 없을 때만 사용하는
Git 추적 고정 스냅샷이다. 날짜별 파일은 경로·수정시각·크기를 캐시 키로 사용하므로,
다운로더가 파일을 교체하면 서버 재시작 없이 다음 요청부터 새 데이터를 읽는다.

다운로드 작업은 추천 API 요청과 분리되어 있으며, AWS 배포 후에도 서버 Scheduler가
정기 실행한다. 구체적인 Scheduler 구현 방식은 배포 환경에 맞게 설정한다.



39. 생활인구도 AWS에서 자동 관리

ML이 사용하는 생활인구 History 역시 지속적으로 갱신해야 한다.

현재 개발환경:

로컬 실행

↓

population_history_maintenance.py

↓

서울 생활인구 API

↓

History 유지

AWS 운영 목표:

AWS Scheduler

↓

population_history_maintenance.py

↓

서울 생활인구 API

↓

누락 날짜 자동 수집

↓

ML용 History 유지

따라서 AWS에서는:

Popup 자동갱신

생활인구 자동 Maintenance

두 정기 작업을 모두 서버가 담당한다.

생활인구 Maintenance 실행시각

Population Maintenance의 실행시각은 서울 생활인구 데이터의 게시 시차를 고려한다.

현재 개발 과정에서 관찰된 패턴에서는 새로운 D-4 생활인구 데이터가 대체로 14:20~14:30 KST 전후에 확인되고 있다.

따라서 AWS에서는 15:00 KST 이후 1차 Maintenance 실행을 우선 검토한다.

게시가 평소보다 늦어지는 경우를 대비해:

15:00 1차 실행

↓

16:00 재시도

↓

17:00 재시도

와 같은 추가 실행을 구성할 수 있다.

이미 필요한 날짜의 데이터가 확보된 경우에는 기존 데이터를 그대로 사용하고, 누락된 날짜가 있는 경우에만 수집을 시도한다.

따라서 반복 실행을 통해 게시 지연에 대응하면서 필요한 History를 보완할 수 있다.

단, 14:20~14:30은 현재 개발 과정에서 관찰된 패턴이며 공식적으로 보장된 게시시각은 아니다.

실제 AWS Scheduler의 실행시각과 재시도 횟수는 배포 시점까지 데이터 게시 패턴을 추가 확인한 뒤 최종 확정한다.



40. 현재 환경과 AWS 운영 목표
항목	현재 개발환경	AWS 운영 목표
FastAPI	로컬	AWS
MySQL	Docker MySQL	운영 MySQL
ML Artifact	저장소 내부	Backend와 함께 배포
생활인구	로컬 관리	AWS 자동 Maintenance
Popup	Windows Scheduler	AWS 자동갱신
환경변수	로컬 .env	AWS 운영환경
데이터 갱신 책임	개발 PC	AWS
개인 PC 종료 영향	일부 존재	없음

핵심 목표는 운영 서비스에서 개발자의 개인 PC 의존성을 완전히 제거하는 것이다.



41. AWS 최종 목표 구조

사용자 요청 처리

Frontend

↓

AWS FastAPI Backend

↓

121 POI + 421 행정동

↓

Citydata + ML

↓

지역 Ranking

↓

실제 장소

↓

코스

DB

FastAPI

↓

운영 MySQL

↓

회원 / 인증 / 사용자 선호

ML 운영 데이터

AWS Scheduler

↓

서울 생활인구 API

↓

Population History

↓

D-4 Direct LightGBM

↓

Backend

Popup 운영 데이터

AWS Scheduler

↓

Popup Data Source

↓

Popup 데이터 자동갱신

↓

FastAPI

즉 사용자의 API 요청 처리와 운영 데이터의 정기 갱신을 분리한다.



42. AWS 배포 시 진행할 작업

AWS 인프라 구조 결정

↓

KOALA 1.1 Backend 배포

↓

Python / Requirements 구성

↓

환경변수 / API Key 설정

↓

운영 MySQL 연결

↓

DATABASE_URL

↓

Alembic Migration

↓

Activity Category Seed

↓

ML Artifact 확인

↓

생활인구 초기 Bootstrap

↓

FastAPI 실행

↓

Population Maintenance Scheduler

↓

Popup Update Scheduler

↓

Frontend 연결

↓

배포환경 전체 E2E 검증

EC2 / RDS / Scheduler 등 구체적인 AWS 서비스는 팀 배포 아키텍처 확정 후 결정한다.



43. AWS에서 추가 확인할 사항
운영 데이터 저장

population_history.csv와 Popup 데이터는 Runtime 중 변경된다.

재배포나 서버 교체 시 데이터가 사라지지 않도록 운영 저장 방식을 결정해야 한다.

다중 Worker

일부 장소 추천 Cursor / Token은 Process Memory를 사용한다.

여러 Worker를 운영한다면 Redis 같은 Shared Store가 필요한지 검토한다.

CORS

Frontend와 Backend가 서로 다른 Origin이면 실제 배포 주소에 맞게 설정한다.

외부 API

API Key 누락이나 외부 API 장애를 운영환경에서 확인할 수 있도록 로그 / 상태 확인 구조도 배포 단계에서 검토한다.



44. 현재 검증 상태

KOALA 1.1 / 2026-09-18 기준

검증 항목	결과
Python 3.14.5 Fresh Clone	PASS
Requirements 설치	PASS
D-4 LightGBM h1~h6 Load	PASS
독립 Docker MySQL	PASS
Alembic	PASS
Activity Seed	PASS
Auth / JWT	PASS
Preferences E2E	PASS
생활인구 Bootstrap	PASS
11일 / 112,728행	PASS
121 + 421 통합	PASS
실제 ML 추론	PASS
ML → Ranking 연결	PASS
실제 장소 추천	PASS
선택 사전검증	PASS
Course 생성	PASS
전체 추천 E2E	PASS
Fresh Clone 재현	PASS
전체 회귀 테스트	410 passed
Subtests	128 passed
Warning	1건

Warning 1건은 기존 Starlette TestClient/httpx 관련 Deprecation Warning이며 기능 실패는 아니다.



45. KOALA 1.1 Freeze

최종 검증 기준 Commit:

1ceb0f4

Freeze Branch:

koala-1.1

team/koala-1.1

현재 이 상태가 KOALA 1.1 개발 완료 기준점이다.



46. 현재 완료된 것과 앞으로 할 것
완료

서울 공식 121 POI 추천
421 행정동 후보 확장
상권 기반 활동 적합도
실제 이동시간 평가
서울 Citydata 혼잡도
생활인구 기반 ML 연구 결과의 서비스 적용
LightGBM 기반 D-4 Direct 모델
+1h ~ +6h Artifact 서비스 통합
생활인구 History 연동
ML Fallback
Final Ranking
실제 장소 추천
장소 선택 사전검증
코스 최적화
회원가입 / 로그인 / JWT
사용자 선호 DB
Docker MySQL
Alembic / Seed
생활인구 Maintenance
Fresh Clone 재현
전체 E2E
KOALA 1.1 Freeze

다음 단계 — AWS

배포
운영 DB 연결
환경변수 / API Key 구성
생활인구 초기 Bootstrap
생활인구 자동 Maintenance
Popup 자동갱신 AWS 이전
운영 데이터 저장방식 결정
Frontend 연결
배포환경 전체 E2E



47. KOALA의 ML 발전과정 한눈에 보기

이 부분이 ML 구조를 가장 간단하게 설명한다.

① 목표

방문 예정시간의 지역 혼잡도를 예측한다.

↓

② 데이터

서울 생활인구 데이터를 구축한다.

↓

③ ML 연구

시간 / 지역 / Lag / Rolling / 변화량 등의 Feature를 구성한다.

↓

④ 기존 모델

LightGBM 기반 미래 혼잡도 예측 모델을 개발하고 검증한다.

↓

⑤ 서비스 적용 검토

실제 KOALA에 모델을 연결한다.

↓

⑥ 문제 발견

서비스 시점에는 최신 생활인구가 항상 확보되지 않는다.

↓

⑦ 기존 모델 유지 방법 검토

최근 시계열을 Profile 등으로 복원하는 방법을 검토한다.

↓

⑧ 운영 문제 확인

데이터 정합성 및 Feature 분포 문제가 발생할 가능성이 확인된다.

↓

⑨ 전략 변경

없는 최신 데이터를 추정하지 않고 실제 확보 가능한 데이터만 사용한다.

↓

⑩ 기존 ML 자산 활용

기존 Feature / Target / 행정동 구조 / LightGBM 모델링 방식을 활용한다.

↓

⑪ D-4 Direct LightGBM

+1h ~ +6h 서비스용 모델을 구성한다.

↓

⑫ Backend 통합

실제 생활인구 History와 후보지역을 모델에 연결한다.

↓

⑬ 서비스 사용

ML 확률 → Congestion Score → Final Score → Ranking



48. 처음 보는 사람이 이것만 기억하면 된다

첫째, KOALA는 지역 → 장소 → 코스 순서로 추천한다.

처음부터 특정 가게 하나만 검색하는 서비스가 아니다.

둘째, 지역 후보는 공식 121 POI와 421 행정동이다.

121개 지역만으로 부족한 서울 지역 범위를 행정동 후보로 확장했다.

셋째, 혼잡도는 후보 종류에 따라 다르게 가져온다.

121 POI는 서울 Citydata를 사용하고, 421 행정동은 생활인구 기반 ML을 사용한다.

넷째, KOALA의 ML은 D-4부터 시작된 것이 아니다.

생활인구를 이용한 Feature Engineering과 LightGBM 기반 미래 혼잡도 예측 모델을 먼저 개발·검증했고, 실제 서비스 적용 과정에서 데이터 제공 시차라는 현실적인 문제가 발견됐다.

다섯째, D-4 Direct는 기존 LightGBM ML을 버린 모델이 아니다.

기존 ML의 데이터 구조, Feature, Target, 행정동 기반 모델링, LightGBM 방식을 활용하면서 실제 서비스에서 확보 가능한 데이터만 사용하도록 재구성한 서비스 적용 모델이다.

여섯째, ML과 Backend의 역할은 다르다.

ML 담당은 혼잡도 예측 모델을 개발하고 검증한다.

Backend 담당은 실제 생활인구와 지역 후보를 모델에 연결하고, 예측 결과를 다른 추천 점수와 결합해 최종 서비스를 만든다.

일곱째, ML 이후에도 서비스는 계속된다.

지역 추천

→ 실제 장소

→ 사용자 선택

→ 실제 이동시간

→ 방문순서

→ 최종 방문 가능 여부

까지 이어진다.

여덟째, DB는 회원과 개인화를 담당한다.

회원가입, 로그인, JWT, 공간·이동수단·활동 선호 등을 관리한다.

아홉째, KOALA 1.1은 현재 개발 검증과 Code Freeze가 완료된 상태다.

Fresh Clone과 전체 E2E를 검증했고 최종 회귀 테스트는 410 passed / 128 subtests passed다.

열째, 다음 큰 단계는 AWS다.

현재 로컬 PC가 담당하고 있는:

Popup 데이터 자동갱신

과

생활인구 History Maintenance

를 AWS로 이전한다.

최종 목표는 개발자의 개인 PC가 꺼져 있어도 Backend, DB, ML 추론, 생활인구 유지, Popup 갱신이 독립적으로 돌아가는 운영환경이다.



문서 기준 및 역할 정의

이 문서는 KOALA 1.1 Code Freeze 시점의 실제 구현 상태와 AWS 배포 후 목표 운영구조를 함께 설명한다.
