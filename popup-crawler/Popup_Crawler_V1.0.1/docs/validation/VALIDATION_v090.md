# v0.9.0 Validation

Validation date: 2026-08-31

## Automated tests

```text
Ran 55 tests
OK
```

## 831-record replay

Input source snapshot:

```text
DayForYou 406
Popga     271
Popply    154
Total     831
```

v0.9 integration replay:

```text
POPUP                  744
NON_POPUP               86
INSUFFICIENT_DATA         1
classification REVIEW     0

auto duplicate edges    160
duplicate REVIEW           0

canonical               594
multi-source             136
3-source                  13

persistent ID reused    594
new persistent ID          0

ACTIVE                   527
UPCOMING                  67
ENDED                      0
UNVERIFIED                 0
```

The result matches the verified v0.8.1 canonical state.

## Duplicate optimization equivalence

The v0.8.1 integration produced 485 duplicate candidate rows.

After the v0.9 safe prefilter optimization:

```text
old candidate count: 485
new candidate count: 485
pair set equal:       YES
full row differences: 0
```

Therefore the optimization changes performance, not duplicate semantics.

On the validation environment, the 831-record integration completed in about 7 seconds after the optimization. Runtime on the user's Windows PC may differ.

## Daily runner reuse smoke test

Command:

```text
python run_daily.py --reuse-latest --no-commit
```

Result:

```text
status: SUCCESS_CANDIDATE
DayForYou count=406
Popga count=271
Popply count=154
canonical=594
classification_review=0
duplicate_review=0
master_committed=False
ACTIVE=527 / UPCOMING=67 / ENDED=0 / UNVERIFIED=0
```

## Daily runner commit smoke test

Using the same validated source snapshot and an existing 594-record master:

```text
status: SUCCESS
canonical=594
persistent ID reused=594
new persistent ID=0
master_committed=True
master history backup created=YES
```

## Safety gates covered by tests

- abnormal source-count drop
- minimum source count
- DayForYou unresolved LLM/manual review
- missing/non-full Popga detail output
- Popply partial detail output
- classification/duplicate REVIEW commit blocking
- clean non-empty canonical commit permission

## Master safety-gate CLI smoke test

A synthetic Popga record deliberately left as `REVIEW` was run with `--commit-master`.

Expected and observed:

```text
classification REVIEW: 1
canonical: 0
Master: BLOCKED
process exit code: 3
existing master file unchanged: YES
```
