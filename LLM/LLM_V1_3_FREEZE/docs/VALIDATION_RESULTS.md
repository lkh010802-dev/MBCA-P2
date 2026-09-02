# V1.3 Freeze Validation Record

Freeze candidate: **V1.3 16-field Luna Hybrid FIX1**

## API validation completed before freeze

| Set | Result |
|---|---:|
| Target Location Focus | 30 / 30 |
| Golden Regression | 50 / 50 |
| Robustness Regression | 30 / 30 |
| **Total API regression/focus** | **110 / 110** |

All reported runs had:
- schema validity: 1.0
- semantic invariant validity: 1.0
- all 16 scalar field accuracies: 1.0 on the final runs
- activity F1: 1.0
- companion F1: 1.0

## Free local safety checks

`python test_postprocess_local.py`
- 7 / 7 PASS

`python validate_v1_3_datasets.py`
- 210 expected cases checked
- schema invalid: 0
- semantic invalid: 0
- postprocess changed a correct expected result: 0

## Interpretation

110/110 is a regression/focus result for the known test sets. It is **not** a blind-generalization score.
The next gate is `tests/blind100_v2`, which must be run once without changing the freeze core first.
