#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Runtime resilience layer for the V1.3.1 parser.

This module intentionally contains NO OpenAI-specific code. It provides:
- total request deadline + one controlled retry
- circuit breaker
- exact-result SQLite cache for time-independent inputs
- conservative deterministic fallback
- runtime metadata/logging helpers

The parser prompt/schema/postprocess policy remains separate from this layer.
"""

from __future__ import annotations

from contextlib import contextmanager

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from intent_postprocess import postprocess_intent

PARSER_VERSION = "1.3.1"

INTENT_DEFAULTS: Dict[str, Any] = {
    "start_location_text": None,
    "target_location_text": None,
    "target_location_scope": None,
    "end_location_text": None,
    "start_time": None,
    "end_time": None,
    "start_time_period": None,
    "end_time_period": None,
    "desired_duration_min_minutes": None,
    "desired_duration_max_minutes": None,
    "activities": [],
    "transport_mode": "auto",
    "companions": [],
    "budget_max": None,
    "budget_preference": None,
    "space_preference": None,
}

# Conservative: if an expression can depend on "now", do not persist/reuse a result cache entry.
_RELATIVE_TIME_RE = re.compile(
    r"지금|현재|방금|이따|곧|오늘|내일|모레|앞으로|지금부터|"
    r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:분|시간|일)\s*(?:뒤|후)"
)

# Fallback cues are intentionally high precision, not comprehensive.
_ACTIVITY_RULES = (
    ("food", re.compile(r"밥|맛집|식사|끼니|먹을\s*(?:것|거)|먹고\s*싶|먹으러")),
    ("cafe", re.compile(r"카페|커피")),
    ("walk", re.compile(r"산책|걷기|걷고\s*싶|걸으며")),
    ("culture", re.compile(r"전시|박물관|미술관|공연")),
    ("entertainment", re.compile(r"방탈출|보드게임|오락실|게임하러|놀이시설")),
    ("shopping", re.compile(r"쇼핑|구매하러")),
    ("drink", re.compile(r"술|맥주|소주|와인|한잔")),
)
_TRANSPORT_WALK_RE = re.compile(r"걸어서|도보(?:로)?|걸어\s*(?:가|갈|이동)")
_TRANSPORT_PUBLIC_RE = re.compile(r"대중교통|지하철|버스")
_TRANSPORT_CAR_RE = re.compile(r"자가용|차\s*(?:가지고|끌고|타고|로\s*가)|운전해서")

_PERIOD_MARK_RE = re.compile(r"(?P<word>아침|점심|저녁|오전|오후)\s*(?:쯤|에|시간대에)")
_PERIOD_ENUM = {"아침": "morning", "점심": "lunch", "저녁": "evening", "오전": "am", "오후": "pm"}
_NEXT_SCHEDULE_RE = re.compile(r"가야\s*해|가야\s*돼|약속(?:이|\s*있)|만나야\s*해|다음\s*일정|일정(?:이|\s*있)")

_COMPANION_AFTER_RE = {
    "partner": re.compile(r"(?:여자친구|남자친구|여친|남친|애인|연인)\s*(?:랑|하고|과|와|이랑|함께)"),
    "friend": re.compile(r"(?:친구|친구들|지인|동기)\s*(?:랑|하고|과|와|이랑|함께)"),
    "family": re.compile(r"(?:가족|부모님|엄마|아빠)\s*(?:랑|하고|과|와|이랑|끼리|함께)"),
    "coworker": re.compile(r"(?:회사\s*동료|직장\s*동료|동료)\s*(?:랑|하고|과|와|이랑|함께)"),
    "child": re.compile(r"(?:아이|아기|자녀)\s*(?:랑|하고|과|와|이랑|데리고|함께)"),
}
_SOLO_RE = re.compile(r"혼자")
_SPACE_INDOOR_RE = re.compile(r"실내")
_SPACE_OUTDOOR_RE = re.compile(r"야외|바깥|밖에서")


@dataclass(frozen=True)
class ResilienceConfig:
    total_deadline_seconds: float = 8.0
    first_attempt_timeout_seconds: float = 5.0
    retry_delay_seconds: float = 0.35
    max_attempts: int = 2
    circuit_failure_threshold: int = 5
    circuit_open_seconds: float = 30.0
    result_cache_enabled: bool = True
    result_cache_ttl_seconds: int = 86400
    result_cache_path: str = ".runtime_cache/intent_result_cache.sqlite3"
    runtime_log_path: str = ""

    @classmethod
    def from_env(cls) -> "ResilienceConfig":
        def _float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except Exception:
                return default

        def _int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except Exception:
                return default

        def _bool(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            total_deadline_seconds=max(1.0, _float("LLM_TOTAL_DEADLINE_SECONDS", 8.0)),
            first_attempt_timeout_seconds=max(0.5, _float("LLM_FIRST_ATTEMPT_TIMEOUT_SECONDS", 5.0)),
            retry_delay_seconds=max(0.0, _float("LLM_RETRY_DELAY_SECONDS", 0.35)),
            max_attempts=max(1, min(2, _int("LLM_MAX_ATTEMPTS", 2))),
            circuit_failure_threshold=max(1, _int("LLM_CIRCUIT_FAILURE_THRESHOLD", 5)),
            circuit_open_seconds=max(1.0, _float("LLM_CIRCUIT_OPEN_SECONDS", 30.0)),
            result_cache_enabled=_bool("LLM_RESULT_CACHE_ENABLED", True),
            result_cache_ttl_seconds=max(60, _int("LLM_RESULT_CACHE_TTL_SECONDS", 86400)),
            result_cache_path=os.getenv("LLM_RESULT_CACHE_PATH", ".runtime_cache/intent_result_cache.sqlite3"),
            runtime_log_path=os.getenv("LLM_RUNTIME_LOG_PATH", ""),
        )


def normalize_input(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "").strip())


def is_time_dependent_input(text: str) -> bool:
    return bool(_RELATIVE_TIME_RE.search(normalize_input(text)))


def make_cache_key(user_input: str, model: str, parser_version: str = PARSER_VERSION) -> str:
    payload = json.dumps(
        {
            "parser_version": parser_version,
            "model": model,
            "input": normalize_input(user_input),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResultCache:
    """Small persistent exact-result cache. Raw user input is not stored."""

    def __init__(self, path: str, ttl_seconds: int, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=0.1)
        conn.execute("PRAGMA busy_timeout=100")
        return conn

    @contextmanager
    def _connection(self):
        """Transaction context that also *closes* SQLite explicitly.

        sqlite3.Connection.__exit__ commits/rolls back but does not guarantee an
        immediate close.  On Windows that can leave the database file locked and
        make TemporaryDirectory cleanup fail with WinError 32.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._lock, self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS result_cache (
                    cache_key TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    intent_json TEXT NOT NULL
                )
                """
            )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = self.clock()
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT expires_at, intent_json FROM result_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if not row:
                return None
            expires_at, raw = row
            if expires_at < now:
                conn.execute("DELETE FROM result_cache WHERE cache_key = ?", (key,))
                return None
            try:
                obj = json.loads(raw)
                return obj if isinstance(obj, dict) else None
            except Exception:
                conn.execute("DELETE FROM result_cache WHERE cache_key = ?", (key,))
                return None

    def put(self, key: str, intent: Dict[str, Any]) -> None:
        now = self.clock()
        raw = json.dumps(intent, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO result_cache(cache_key, created_at, expires_at, intent_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    intent_json=excluded.intent_json
                """,
                (key, now, now + self.ttl_seconds, raw),
            )


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int,
        open_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.monotonic = monotonic
        self._lock = threading.Lock()
        self._state = self.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN and self.monotonic() - self._opened_at >= self.open_seconds:
                return self.HALF_OPEN
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            now = self.monotonic()
            if self._state == self.CLOSED:
                return True
            if self._state == self.OPEN:
                if now - self._opened_at < self.open_seconds:
                    return False
                self._state = self.HALF_OPEN
            if self._state == self.HALF_OPEN:
                if self._probe_in_flight:
                    return False
                self._probe_in_flight = True
                return True
            return False

    def on_success(self) -> None:
        with self._lock:
            self._state = self.CLOSED
            self._consecutive_failures = 0
            self._opened_at = 0.0
            self._probe_in_flight = False

    def on_failure(self) -> None:
        with self._lock:
            self._probe_in_flight = False
            self._consecutive_failures += 1
            if self._state == self.HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = self.monotonic()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = self._state
            if state == self.OPEN and self.monotonic() - self._opened_at >= self.open_seconds:
                state = self.HALF_OPEN
            return {"state": state, "consecutive_failures": self._consecutive_failures}


def deterministic_fallback(user_input: str, runtime_context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], list]:
    """High-precision fallback. Unknown fields remain null/[]/auto."""
    text = normalize_input(user_input)
    intent = json.loads(json.dumps(INTENT_DEFAULTS, ensure_ascii=False))

    activities = []
    for label, pattern in _ACTIVITY_RULES:
        if pattern.search(text) and label not in activities:
            activities.append(label)
    intent["activities"] = activities

    if _TRANSPORT_CAR_RE.search(text):
        intent["transport_mode"] = "car"
    elif _TRANSPORT_PUBLIC_RE.search(text):
        intent["transport_mode"] = "public_transit"
    elif _TRANSPORT_WALK_RE.search(text):
        intent["transport_mode"] = "walk"

    companions = []
    if _SOLO_RE.search(text):
        companions.append("solo")
    else:
        # If "그 전에" exists, appointment people before it are not current companions.
        companion_scope = text.split("그 전에", 1)[1] if "그 전에" in text else text
        for label, pattern in _COMPANION_AFTER_RE.items():
            if pattern.search(companion_scope) and label not in companions:
                companions.append(label)
    intent["companions"] = companions

    if _SPACE_INDOOR_RE.search(text) and not _SPACE_OUTDOOR_RE.search(text):
        intent["space_preference"] = "indoor"
    elif _SPACE_OUTDOOR_RE.search(text) and not _SPACE_INDOOR_RE.search(text):
        intent["space_preference"] = "outdoor"

    period_marks = list(_PERIOD_MARK_RE.finditer(text))
    if period_marks:
        # Prefer end endpoint when the marked period is close to a later-schedule cue.
        assigned_end = False
        for cue in _NEXT_SCHEDULE_RE.finditer(text):
            candidates = [m for m in period_marks if m.end() <= cue.start() and cue.start() - m.end() <= 48]
            if candidates:
                intent["end_time_period"] = _PERIOD_ENUM[candidates[-1].group("word")]
                assigned_end = True
                break
        if not assigned_end and len(period_marks) == 1:
            intent["start_time_period"] = _PERIOD_ENUM[period_marks[0].group("word")]

    # Reuse the already regression-tested deterministic postprocessor for safe duration,
    # endpoint-period, walking-transport and scope invariants.
    final_intent, changes = postprocess_intent(text, runtime_context or {}, intent)
    return final_intent, changes


def append_runtime_log(path: str, metadata: Dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = dict(metadata)
    record["logged_at_unix"] = time.time()
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def empty_usage() -> Dict[str, int]:
    return {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "uncached_nonwrite_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }

class LocalOutputError(RuntimeError):
    """LLM response arrived but failed local JSON/schema/semantic validation."""


def execute_with_resilience(
    *,
    user_input: str,
    runtime_context: Optional[Dict[str, Any]],
    model: str,
    call_llm: Callable[[float], Dict[str, Any]],
    is_retryable_error: Callable[[Exception], bool],
    validate_intent: Callable[[Dict[str, Any]], None],
    config: ResilienceConfig,
    circuit: CircuitBreaker,
    cache: Optional[ResultCache] = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """Execute the LLM path with a bounded deadline and safe fallback path.

    call_llm(timeout_seconds) must return a mapping with at least `intent`.
    The returned mapping always contains `intent`, debug fields, and `runtime` metadata.
    """
    started = monotonic()
    static_cacheable = config.result_cache_enabled and not is_time_dependent_input(user_input)
    cache_key = make_cache_key(user_input, model) if static_cacheable else None
    errors = []
    attempts = 0

    def _meta(source: str, *, cache_hit: bool, fallback_used: bool) -> Dict[str, Any]:
        elapsed_ms = int(max(0.0, monotonic() - started) * 1000)
        last = errors[-1] if errors else None
        return {
            "parser_version": PARSER_VERSION,
            "source": source,
            "attempts": attempts,
            "latency_ms": elapsed_ms,
            "result_cache_hit": cache_hit,
            "cache_eligible": static_cacheable,
            "fallback_used": fallback_used,
            "prompt_cache_hit": False,
            "circuit": circuit.snapshot(),
            "error_type": last.get("type") if last else None,
            "error_status": last.get("status") if last else None,
        }

    def _cache_or_fallback() -> Dict[str, Any]:
        if static_cacheable and cache is not None and cache_key:
            try:
                cached = cache.get(cache_key)
            except Exception:
                cached = None
            if cached is not None:
                try:
                    validate_intent(cached)
                    payload = {
                        "intent": cached,
                        "llm_intent": None,
                        "postprocess_changes": [],
                        "usage": empty_usage(),
                        "request_id": None,
                    }
                    payload["runtime"] = _meta("result_cache", cache_hit=True, fallback_used=False)
                    append_runtime_log(config.runtime_log_path, payload["runtime"])
                    return payload
                except Exception:
                    # A corrupt/stale cache entry is ignored; fallback remains conservative.
                    pass

        fallback_intent, fallback_changes = deterministic_fallback(user_input, runtime_context)
        validate_intent(fallback_intent)
        payload = {
            "intent": fallback_intent,
            "llm_intent": None,
            "postprocess_changes": fallback_changes,
            "usage": empty_usage(),
            "request_id": None,
        }
        payload["runtime"] = _meta("deterministic_fallback", cache_hit=False, fallback_used=True)
        append_runtime_log(config.runtime_log_path, payload["runtime"])
        return payload

    # OPEN circuit: do not spend time/tokens trying the API.
    if not circuit.allow_request():
        return _cache_or_fallback()

    for attempt in range(1, config.max_attempts + 1):
        attempts = attempt
        elapsed = monotonic() - started
        remaining = config.total_deadline_seconds - elapsed
        if remaining < 0.5:
            break

        if attempt == 1:
            attempt_timeout = min(config.first_attempt_timeout_seconds, remaining)
        else:
            attempt_timeout = remaining
        attempt_timeout = max(0.5, attempt_timeout)

        try:
            payload = call_llm(attempt_timeout)
            if not isinstance(payload, dict) or not isinstance(payload.get("intent"), dict):
                raise LocalOutputError("LLM payload missing intent dict")
            validate_intent(payload["intent"])
            circuit.on_success()

            if static_cacheable and cache is not None and cache_key:
                try:
                    cache.put(cache_key, payload["intent"])
                except Exception:
                    # Cache persistence must never fail the user request.
                    pass

            payload.setdefault("llm_intent", None)
            payload.setdefault("postprocess_changes", [])
            payload.setdefault("usage", empty_usage())
            payload.setdefault("request_id", None)
            payload["runtime"] = _meta("llm", cache_hit=False, fallback_used=False)
            payload["runtime"]["prompt_cache_hit"] = bool((payload.get("usage") or {}).get("cached_input_tokens", 0))
            append_runtime_log(config.runtime_log_path, payload["runtime"])
            return payload
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            errors.append({"type": exc.__class__.__name__, "status": status})
            circuit.on_failure()

            if attempt >= config.max_attempts or not is_retryable_error(exc):
                break
            if circuit.snapshot()["state"] == CircuitBreaker.OPEN:
                break

            remaining = config.total_deadline_seconds - (monotonic() - started)
            if remaining <= config.retry_delay_seconds + 0.5:
                break
            if config.retry_delay_seconds:
                sleeper(min(config.retry_delay_seconds, max(0.0, remaining - 0.5)))

    return _cache_or_fallback()
