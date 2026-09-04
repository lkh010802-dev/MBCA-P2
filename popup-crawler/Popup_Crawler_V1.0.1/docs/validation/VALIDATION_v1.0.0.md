# v1.0.0 Release Validation

Date: 2026-09-01

## Baseline

v1.0.0 freezes the v0.9.7 crawler/integration behavior and adds release/operations packaging plus Windows scheduled execution.

## Automated regression tests

```text
Ran 92 tests
OK
```

Coverage includes:

- DayForYou/Popga/Popply parsing
- detail enrichment and cache policy
- Popply hydration recovery/quarantine/status refresh gates
- popup/non-popup classification
- duplicate candidate/merge safety
- human decisions
- persistent popup_id reuse
- master lifecycle and retirement
- daily change tracking
- backend CSV export
- v1.0 scheduler/release contract files

## Python compile check

All Python source/test modules compiled successfully with `py_compile` in the release build environment.

## Secret scan

The release directory contains `.env.example` only. No real OpenAI API key is packaged.

## Backend export surface

`storage/csv_export.py` exposes 31 explicit fields and writes UTF-8 BOM CSV only after successful master commit.

## Scheduler release contract

- `run_daily_scheduled.bat` contains no `pause`
- default schedule: daily 08:00
- task name: `PopupCrawlerDaily`
- StartWhenAvailable/WakeToRun enabled
- scheduler wrapper logs written under `logs/scheduler/`

## Windows note

The Task Scheduler registration scripts were statically validated and are designed for Windows PowerShell + ScheduledTasks module. Actual task registration must be verified once on the target Windows machine with `setup_daily_schedule.bat` then `check_daily_schedule.bat`.
