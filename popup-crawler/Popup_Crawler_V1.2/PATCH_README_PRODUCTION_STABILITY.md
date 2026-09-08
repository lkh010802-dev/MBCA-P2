# Popup Crawler v1.2 Production Stability Patch

이 패치는 매일 새로운 예외가 1~10건 생길 때마다 전체 수집이 막히고 코드를 다시 고치는 구조를 끝내기 위한 운영 안정화 패치입니다.

## 핵심 변경

1. **중복 REVIEW는 소량이면 전체 실패시키지 않습니다.**
   - 애매한 중복 관련 레코드만 `duplicate_quarantine.jsonl`로 격리합니다.
   - 격리된 레코드는 당일 backend CSV/JSON에 넣지 않습니다.
   - 기존 master에 이미 있던 같은 source 레코드는 삭제/종료 처리하지 않고 보호합니다.
   - REVIEW가 갑자기 대량 발생할 때만 parser/source 이상으로 보고 전체 반영을 차단합니다.

2. **2026-09-08에 실제 발생한 중복 패턴을 규칙으로 보강했습니다.**
   - 아마이모찌도넛/보따리제과점 editorial alias cluster
   - 명탐정 코난 동일 콜라보 카페 3-source cluster
   - 개구리 중사 케로로 DayForYou 재게시물
   - 같은 구역이지만 실제 도로 주소가 다른 지점은 자동 병합하지 않음
   - `콜라보카페` 같은 일반 형식 태그는 고유 브랜드 증거로 사용하지 않음

3. **Master를 코드 폴더 밖에 영구 저장합니다.**
   - 예약/서버 실행 시 기본 상태 폴더: `..\Popup_Crawler_STATE\`
   - Master: `..\Popup_Crawler_STATE\canonical_master.jsonl`
   - 버전 폴더를 교체해도 popup_id와 이전 상태가 유지됩니다.

4. **Master가 사라진 채 서버가 시작되는 것을 막습니다.**
   - 외부 master가 처음 만들어질 때 기존 `data\master\canonical_master.jsonl`을 우선 복사합니다.
   - 그것도 없으면 최신 `output\*_popup.csv`에서 기존 `popup_id`와 `source_refs`를 복구합니다.
   - 이전 master/CSV가 하나도 없으면 production run은 크롤링 전에 멈춥니다.
   - 정말 첫 서버 구축인 경우에만 `POPUP_ALLOW_MASTER_BOOTSTRAP=1`을 한 번 사용합니다.

## 적용

현재 `Popup_Crawler_V1.1` 폴더에 이 ZIP의 내용물을 그대로 덮어씁니다.

덮어쓴 뒤 **처음 한 번만**:

```bat
MIGRATE_PRODUCTION_STATE.bat
```

`[OK] Production state is ready.`가 나오면:

```bat
CHECK_PRODUCTION_STATE.bat
```

으로 master 행 수를 확인합니다.

그 뒤 n8n을 평소대로 실행합니다. `run_daily_scheduled.bat`와 `run_daily_n8n.bat` 모두 외부 production state를 자동 사용합니다.

## 서버 배포에서 절대 지우면 안 되는 폴더

```text
Popup_Crawler_STATE\
```

코드 폴더(`Popup_Crawler_V1.1`, 이후 V1.2 등)는 교체해도 되지만, `Popup_Crawler_STATE`는 서버의 영구 데이터입니다. 백업 대상에도 포함하세요.

## REVIEW 운영 정책

앞으로 새로운 애매한 팝업이 몇 건 생겨도:

```text
새 REVIEW 발생
→ 해당 레코드만 quarantine
→ 나머지 안전한 데이터 Master/CSV 반영
→ 서버 정상 운영 계속
```

입니다. 따라서 일반적인 신규 예외 때문에 매일 코드를 수정할 필요가 없습니다. REVIEW 큐는 필요할 때 묶어서 점검하면 됩니다.

## DayForYou 속도

예약/n8n 실행에서는 DayForYou 상세 HTML 캐시도 `Popup_Crawler_STATE\dayforyou_detail_html`에 저장합니다.
기본 TTL은 54시간입니다.

- 신규 source_id 또는 54시간이 지난 상세: live fetch
- 최근 상세: local cache reparse
- 목록 자체는 매일 새로 가져옵니다.

따라서 첫 실행/캐시가 비어 있는 배포 직후에는 몇 분 걸릴 수 있지만, 이후 실행은 335개 상세를 매번 전부 다시 다운로드하지 않습니다.
`DAYFORYOU_DETAIL_CACHE_HOURS`로 TTL을 조정할 수 있습니다.
