# KOALA extension settings

The upstream backend under `backend/core` stays unchanged. Optional extension
settings belong in `backend/core/.env`, because `backend/run.py` starts the
upstream application from that directory.

To enable place images through NAVER API HUB Image Search, add these server-side variables:

```dotenv
NAVER_CLIENT_ID=your-client-id
NAVER_CLIENT_SECRET=your-client-secret
```

The credentials are read only by the backend and are never returned to the
browser. Without both values, image enrichment is disabled and the existing
category image remains in use. Search results and verified image files are
cached under the system temporary directory's `KOALA/cache` folder for seven days; failed lookups are
cached for one hour. `KOALA_CACHE_DIR` can override that location.
