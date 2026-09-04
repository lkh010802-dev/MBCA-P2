# v0.8.1 validation

Date: 2026-08-31

## Changes
- Human classification decisions:
  - `popply:4924` Attack on Titan FINAL -> `NON_POPUP`
  - `popga:7286` Ongredients long-term flagship/VIP lounge -> `NON_POPUP`
- Master reconciliation can retire a previously accepted canonical row when all of its known source refs are explicitly classified `NON_POPUP`.
- Multi-source rows are protected: a row is not retired when only some of its source refs are retired.

## Automated tests
- 48 tests passed.

## 831-record replay against the previously committed v0.8 master

```text
POPUP 744 / NON_POPUP 86 / INSUFFICIENT 1
classification review: 0
auto duplicate edges: 160
duplicate review: 0
canonical today: 594
persistent ID reused: 594
new persistent ID: 0
retired existing master non-popup: 2
lifecycle: ACTIVE 527 / UPCOMING 67 / ENDED 0 / UNVERIFIED 0
LLM calls: 0
```

Expected effect: the two human-confirmed non-popup records are removed from the proposed master instead of being incorrectly carried as `UNVERIFIED`.
