# V1.3 Blind100 v2 — Historical First-run Record

이 세트는 V1.3 Freeze가 처음 보는 100문장에서 얼마나 일반화되는지 확인한 역사적 Blind 세트입니다.

## 공식 기록

- V1.3 Freeze first unseen run: **97/100**
- 실패 3건 확인 후 V1.3.1 deterministic postprocess로 보정
- 동일 100건 reprocessed regression: **100/100**

따라서 100/100은 새로운 blind score가 아니라 기존 실패를 반영한 regression 결과입니다. 최초 97/100을 삭제하거나 100/100으로 대체하지 않습니다.

## 당시 실패 3건

1. `경복궁에서 구경하고 저녁쯤 광화문 가야 해`
   - generic `구경`을 `culture`로 과잉추론
2. `오전에 북촌에서 산책하고 싶어`
   - `오전`을 `morning`으로 잘못 분류 (`am`이 정답)
3. `지금부터 한두 시간 뭐할까?`
   - desired duration 60~120 대신 availability/end_time으로 오해

## 현재 V1.3.1 상태

위 3건은 deterministic postprocess로 보정되며, prompt/schema는 V1.3과 동일하게 유지됩니다.
