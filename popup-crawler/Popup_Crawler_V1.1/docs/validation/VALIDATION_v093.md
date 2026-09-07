# v0.9.3 Validation

## Goal

Add persistent-ID-based daily change tracking without changing v0.9.2 crawling, classification, duplicate merge, or master safety behavior.

## Change categories

- new popup
- newly ended
- reappeared
- newly unverified
- tracked field changes
- source coverage changes
- retired master rows

## Tests

```text
Ran 70 tests
OK
```

New v0.9.3 tests verify:

1. Same committed snapshot compared again -> zero changes.
2. New popup -> exactly one `new` event.
3. Date/field update -> before/after values are preserved.
4. Source coverage expansion -> `source_changes` recorded.
5. ACTIVE disappearing -> `UNVERIFIED` alert only once.
6. ACTIVE -> ENDED -> ended alert only once.
7. UNVERIFIED -> ACTIVE -> reappeared event.
8. Master row removal -> retired event.

## Output

```text
data/integration/runs/<timestamp>/daily_changes.json
data/integration/runs/<timestamp>/changes/*.jsonl
data/daily/latest_changes.json
```

The daily summary also surfaces counts and up to five names for the main change categories.
