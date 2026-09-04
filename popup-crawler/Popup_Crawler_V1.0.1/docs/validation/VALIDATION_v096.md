# v0.9.6 Validation — small Popply detail quarantine

Observed production case on 2026-09-01:

- Popply candidates: 149
- detail failed/core incomplete: 1
- v0.9.5 blocked the entire daily integration before merge

v0.9.6 changes the source-quality policy:

- raw/audit `normalized_with_details.jsonl` still preserves every candidate
- detail-failed/core-incomplete rows are written to `detail_quarantine.jsonl`
- only complete rows are written to `normalized_for_integration.jsonl`
- small quarantine is allowed when both conditions are met:
  - incomplete count <= 2
  - incomplete rate <= 2%
- larger failures still block master/CSV commit

This means a 1/149 hydration failure no longer prevents the other 148 valid Popply rows from being merged. A unique quarantined popup may be absent from that day's backend CSV, while an existing master record naturally remains protected by lifecycle/unverified logic.

Automated validation:

```text
Ran 84 tests
OK
```

Tests include:
- 1/149 incomplete => warning + quarantine, no source-quality block
- 4/149 incomplete => block
- integration uses `normalized_for_integration.jsonl`
- previous v0.9.5 CSV/status-filter guards remain intact
