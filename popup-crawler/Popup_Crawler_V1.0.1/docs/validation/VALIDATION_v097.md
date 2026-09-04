# v0.9.7 Validation — 2026-09-01 duplicate review resolution

User integration run `20260901_112216` produced exactly 3 duplicate REVIEW pairs, all classification conflicts with exact name/date/address identity.

Resolved as NON_POPUP:

1. `popga:8695` ↔ `popply:5874` — 2026 아덕페 / 아이파크몰 덕후 페스티벌
   - whole record is a multi-program festival (card show, hobby show, market, photo zone, game event)
   - the Jujutsu Kaisen × Reclow popup is only one sub-program
   - Popply classification overridden to NON_POPUP

2. `popga:8778` ↔ `popply:5893` — Identity V Winter Festival Fair @ Hongdae
3. `popga:8779` ↔ `popply:5892` — Identity V Winter Festival Fair @ Jamsil
   - held inside existing Animate stores
   - merchandise release + purchase benefit fair
   - not treated as an independent temporary popup store
   - Popga classifications overridden to NON_POPUP

Replay against the uploaded `common_records.jsonl` with the existing decision file plus these three overrides produced `duplicate_review=0`.
