"""Small compatibility layer used by the local backend extensions."""

from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger("koala.audit")


def record(event: str, **fields) -> None:
    logger.info("%s %s", event, json.dumps(fields, ensure_ascii=False, default=str))


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        trace_id = request.headers.get("X-Koala-Trace-Id") or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            record("request_error", trace_id=trace_id, path=request.url.path)
            raise
        response.headers["X-Koala-Trace-Id"] = trace_id
        record(
            "request_complete",
            trace_id=trace_id,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
        return response

