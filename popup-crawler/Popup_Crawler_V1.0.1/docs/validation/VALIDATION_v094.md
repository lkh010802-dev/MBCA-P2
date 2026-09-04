# v0.9.4 Validation — 2026-09-01 first daily transition

## Input analyzed

User integration run: `20260901_094208`

v0.9.3 report:

- source records: 635 (DayForYou 255 / Popga 246 / Popply 134)
- POPUP 565 / NON_POPUP 65 / INSUFFICIENT 1
- classification REVIEW 4
- duplicate REVIEW 23
- canonical candidate 467
- persistent reused 424 / provisional new 43
- lifecycle ACTIVE 376 / UPCOMING 91 / ENDED 177 / UNVERIFIED 1
- master commit: BLOCKED

## Persistent-ID/lifecycle sanity

Previous committed master: 602.

`424 reused + 177 newly ended + 1 unverified = 602`

All 177 `newly_ended` records have `end_date=2026-08-31`. This confirms the large end-of-month transition itself is legitimate and not a mass identity failure.

## Root cause of REVIEW spike

Popply current run had 33 detail records where:

- `detail_fetch_ok=True`
- address missing
- title detail missing
- start/end detail missing
- description missing

32 were UPCOMING and 1 ACTIVE. v0.9.2 executed 38 live Popply detail requests, so most live requests captured a hydration skeleton rather than the populated DOM.

All 23 duplicate REVIEW edges involved a Popply side missing core detail. The typical edge had exact name and exact dates but no address, dropping an otherwise automatic Popga↔Popply merge into REVIEW.

## Historical cache recovery test

Using the valid 8/31 Popply output:

- corrupt current Popply core-detail rows: 33
- exact source_id/title/date match with valid 8/31 detail: 25
- new IDs requiring live refetch: 8

After replacing only those 25 rows with identity-matching historical valid detail and applying v0.9.4 rules:

- classification REVIEW fell from 4 to 2
- duplicate REVIEW fell from 23 to 5

The remaining 5 duplicate review edges all correspond to new Popply IDs that did not exist in the 8/31 cache:

- 퍼퓨라운지 팝업
- OKT × SOAP 팝업
- 모에브 팝업
- 2026 시크릿 도서전
- 스포티파이 하우스 서울

Each has an exact-date/name Popga counterpart with full address. A successful v0.9.4 live detail hydration is therefore expected to restore the strong identity evidence and resolve most/all remaining reviews without LLM.

## Classification corrections validated

v0.9.4 generic rules correct these observed false positives:

- DayForYou `The Best Class 앨리스 발레` → NON_POPUP
- DayForYou `바른 자세... 성인발레` → NON_POPUP
- DayForYou `춤추는 가을... 댄스 클래스` → NON_POPUP
- DayForYou two `위클리 라이징 케이팝 스타` entries → NON_POPUP
- malformed `장소: 주한 이탈리아 대사관저...` → INSUFFICIENT_DATA
- Popply `ODCF 2026` festival → NON_POPUP
- Popga `2026 아덕페 - 아이파크몰 덕후 페스티벌` → NON_POPUP; its description mentions a sub-popup, but the whole record is a festival.

## Regression guard: exhibition popup

Do not hard-negative every title containing `전시`.

Actual 9/1 Popga evidence:

- `기븐 전시` (STORE): description explicitly says `Pop Up Shop`; remains POPUP.
- `LG전자 브랜드 전시 - THE FIRST : Origins` (STORE): description says `헤리티지 전시 팝업`; DayForYou and Popply also contain the same popup; remains POPUP.

New automated test protects these cases while still hard-negating whole-event festival titles.

## Daily source semantics

The old master historically accumulated `sources`, which made source removals invisible. v0.9.4 separates:

- cumulative refs for persistent identity
- current-run refs/sources for daily source coverage change
- historical `sources_ever`

## Automated tests

```text
Ran 79 tests
OK
```

Tests cover core hydration completeness, old valid cache recovery, live-error cache recovery, quality-gate blocking, festival false-positive correction, exhibition-popup regression, DayForYou class/broken-title filtering, and current-vs-ever source tracking.
