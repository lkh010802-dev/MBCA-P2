# v0.8.0 Validation

Validation basis: the real 2026-08-31 3-source integration run supplied from v0.7.1.

## Input

- DayForYou: 406
- Popga: 271
- Popply: 154
- Total: 831 source records

## v0.8 classification

- POPUP: 746
- NON_POPUP: 84
- INSUFFICIENT_DATA: 1
- REVIEW / UNCERTAIN requiring manual classification: 0

The one insufficient record is `popply:5434` / `올드페리도넛 성수`: the detail description is missing and the period is long, so the program does not force a popup/non-popup answer.

## Duplicate / canonical

- AUTO_DUPLICATE edges: 160
- Remaining duplicate review: 2
- Canonical today: 596
- Multi-source canonical: 136
- Three-source canonical: 13

Remaining duplicate review pairs are intentionally conservative:

1. `진격의 거인 전시` vs `진격의 거인展 FINAL 팝업` — same place/dates but source classification conflicts.
2. `온그리디언츠 팝업 - 이너글로우 VIP 라운지` vs `온그리디언츠 플래그십 스토어` — same place/dates but popup lounge vs permanent flagship semantics conflict.

## Persistent master

First build from the 596 canonical records:

- persistent ID reused: 0
- new persistent IDs: 596

Second build with the same canonical set:

- persistent ID reused: 596
- new persistent IDs: 0

This verifies that `popup_id` remains stable when the same source references are seen again.

## Lifecycle on 2026-08-31

- ACTIVE: 529
- UPCOMING: 67
- ENDED: 0
- UNVERIFIED: 0

Open-ended records (`end_date=null`) are supported. If such a record disappears from a later crawl, it becomes `UNVERIFIED` rather than being incorrectly marked ended.

## Regression tests

46 tests passed.

## JSONL U+2028 hotfix

All integration JSONL loading uses physical newline streaming. Valid Unicode line-separator characters inside JSON strings no longer break records.
