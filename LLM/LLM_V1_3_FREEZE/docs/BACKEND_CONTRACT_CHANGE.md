# V1.3 Backend Contract Change

Backend FINAL changes the output contract from 14 to 16 fields by adding:

- `target_location_text`: location explicitly designated for the current recommended activity.
- `target_location_scope`: `area` or `place`; null iff target location is null.

The backend FINAL also expands availability vs desired-duration examples. Those rules were already present in the V1.2 Luna Hybrid line, so V1.3 keeps the compact V1.2 wording rather than restoring the long V1.1 prompt.

## Location roles
- start: future position / schedule end from which activity can start.
- target: explicit activity destination.
- end: mandatory next destination.

V1.2 Freeze is historical and remains unchanged. V1.3 is a new candidate and requires fresh API regression before Freeze.
