# v0.9.5 Validation — backend CSV + Popply status refresh guard

## Why this version exists

The 2026-09-01 v0.9.4 daily run reported Popply candidate_count=97 only ~25 minutes after a prior run had 134 candidates. The v0.9.4 summary also showed cache/live=96/1, strongly suggesting that almost only ACTIVE cards were collected and the UPCOMING filter cards may not have refreshed before parsing.

v0.9.5 therefore treats the filter label and the rendered card set as separate state:

- after a status filter change, wait for actual card signature change;
- scroll longer until the rendered card count is stable;
- compare source_id overlap between consecutive statuses;
- retry a suspicious status once after page reload;
- if card refresh still looks stale, block daily master commit rather than silently publishing an incomplete snapshot.

## Backend CSV

On a successful committed integration, v0.9.5 writes:

`output/YYYYMMDD_popup.csv`

The CSV contains only canonical rows seen in the latest run whose current status is ACTIVE or UPCOMING. ENDED and UNVERIFIED history remains in `data/master` and is not mixed into the backend-facing daily snapshot.

CSV properties:

- persistent `popup_id`
- UTF-8 with BOM for direct Korean Excel opening
- explicit stable field order
- nested lists/dicts serialized as compact JSON strings
- `sources` flattened as `dayforyou|popga|popply`
- same-day successful rerun atomically replaces the same dated file
- BLOCKED/no-commit runs do not publish the dated CSV

## Regression tests

```text
Ran 82 tests
OK
```

New tests cover:

- status-card overlap detection;
- daily quality-gate blocking when Popply status cards remain stale after retry;
- backend CSV exports ACTIVE/UPCOMING only;
- UTF-8 BOM and stable source flattening.

## Snapshot smoke test

Using the 2026-09-01 09:42 integration snapshot, the CSV exporter accepted 467 current canonical rows and exported 467 rows with the expected header. This validates serialization independently of a fresh network crawl.
