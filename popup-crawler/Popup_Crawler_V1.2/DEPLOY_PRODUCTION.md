# Production deployment rules

- **Code** and **state** are separate.
- Replace/update the crawler code folder when deploying.
- Never delete `Popup_Crawler_STATE` beside the code folder.
- `canonical_master.jsonl` is the persistent identity/history source.
- Small classification/duplicate ambiguity is quarantined, not globally fatal.
- A large quarantine spike still blocks publishing because it can indicate a source/parser regression.
- `output/*.csv` is a daily delivery artifact, not the persistent database.
- Before a deploy, back up `Popup_Crawler_STATE`.

Recommended layout:

```text
popup-crawler\
  Popup_Crawler_V1.1\        # replaceable application code
  Popup_Crawler_STATE\       # persistent, never replace during deploy
    canonical_master.jsonl
    .popup_master_initialized
    history\                  # created after subsequent commits
    views\
```

The state folder also contains the persistent DayForYou detail HTML cache. This is performance state rather than identity state, but keeping it avoids a full 300+ detail live fetch after every deployment.
