# Coordinate Hotfix 2026-09-03

## What was reproduced

The same three popup IDs remained unresolved in both the 2026-09-02 backfill output and the 2026-09-03 daily CSV.

1. `popup_2e377c519c0f62b8` - free-form Yongsan I'Park Mall address
2. `popup_499cfc797898120e` - hashtag-style Yongsan I'Park Mall address
3. `popup_7b6a27d7ebf2b378` - numbered-gil road address rendered as `백제고분로 41길 24`

## Root causes

- The old road regex interpreted the `41` in `백제고분로 41길 24` as a building number, producing the incorrect base `서울 송파구 백제고분로 41`.
- Free-form venue strings had no `address_base`/`venue_name`, so the fallback sent overly noisy source text instead of a concise place query.

## Fix

- Normalize `...로 41길 24` -> `...로41길 24` before extracting `address_base`.
- Re-derive `address_base` from the full address even when an older source value is already present.
- Infer colloquial district stems such as `서울 용산 ...` -> `용산구` for validation only.
- Generate concise place queries such as `용산 아이파크몰 서울` and `용산아이파크몰 서울`.
- Try `address_base` through Kakao keyword search if Kakao address search misses.
- Preserve the existing 31-column backend CSV schema.

## Backfill

```powershell
.\.venv\Scripts\python.exe backfill_coordinates.py output/20260903_popup.csv
```

The unresolved CSV now includes diagnostic columns showing which address/keyword queries would be used and why a row remained unresolved.
