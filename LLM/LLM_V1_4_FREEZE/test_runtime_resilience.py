#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Zero-API fault-injection tests for the runtime resilience layer."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

from runtime_resilience import (
    CircuitBreaker,
    INTENT_DEFAULTS,
    ResilienceConfig,
    ResultCache,
    deterministic_fallback,
    execute_with_resilience,
    is_time_dependent_input,
    make_cache_key,
)

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "user_intent_schema_team_v1_3_STRICT.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def advance(self, seconds):
        self.t += seconds


class TransientError(RuntimeError):
    status_code = 503


class NonRetryableError(RuntimeError):
    status_code = 400


def validate(intent):
    errors = list(VALIDATOR.iter_errors(intent))
    assert not errors, errors[0].message if errors else ""
    if intent["target_location_text"] is None:
        assert intent["target_location_scope"] is None
    lo, hi = intent["desired_duration_min_minutes"], intent["desired_duration_max_minutes"]
    if lo is not None and hi is not None:
        assert lo <= hi


def payload(**overrides):
    intent = copy.deepcopy(INTENT_DEFAULTS)
    intent.update(overrides)
    return {
        "intent": intent,
        "llm_intent": copy.deepcopy(intent),
        "postprocess_changes": [],
        "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 90,
            "cache_write_input_tokens": 0,
            "uncached_nonwrite_input_tokens": 10,
            "output_tokens": 20,
            "reasoning_tokens": 0,
            "total_tokens": 120,
        },
        "request_id": "req_test",
    }


def config(cache_path, **overrides):
    base = dict(
        total_deadline_seconds=8.0,
        first_attempt_timeout_seconds=5.0,
        retry_delay_seconds=0.35,
        max_attempts=2,
        circuit_failure_threshold=5,
        circuit_open_seconds=30.0,
        result_cache_enabled=True,
        result_cache_ttl_seconds=60,
        result_cache_path=str(cache_path),
        runtime_log_path="",
    )
    base.update(overrides)
    return ResilienceConfig(**base)


def run_case(name, fn, results):
    try:
        fn()
        results.append((name, True, ""))
    except Exception as exc:
        results.append((name, False, f"{exc.__class__.__name__}: {exc}"))


def main():
    results = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def fresh(threshold=5, ttl=60):
            clock = FakeClock()
            cfg = config(root / f"cache_{len(results)}.sqlite3", circuit_failure_threshold=threshold, result_cache_ttl_seconds=ttl)
            cb = CircuitBreaker(threshold, cfg.circuit_open_seconds, monotonic=clock.monotonic)
            cache = ResultCache(cfg.result_cache_path, cfg.result_cache_ttl_seconds, clock=clock.time)
            return clock, cfg, cb, cache

        def execute(text, call, clock, cfg, cb, cache, retryable=lambda e: isinstance(e, TransientError)):
            return execute_with_resilience(
                user_input=text,
                runtime_context={"current_datetime": "2026-09-02T17:00:00+09:00", "timezone": "Asia/Seoul"},
                model="gpt-5.6-luna",
                call_llm=call,
                is_retryable_error=retryable,
                validate_intent=validate,
                config=cfg,
                circuit=cb,
                cache=cache,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
            )

        def c1():
            clock, cfg, cb, cache = fresh()
            calls=[]
            out=execute("홍대에서 카페 가고 싶어", lambda t:(calls.append(t) or payload(activities=["cafe"])), clock,cfg,cb,cache)
            assert out["runtime"]["source"]=="llm" and out["runtime"]["attempts"]==1 and len(calls)==1
            assert out["runtime"]["prompt_cache_hit"] is True
        run_case("normal_success_one_call", c1, results)

        def c2():
            clock,cfg,cb,cache=fresh(); n={"v":0}; timeouts=[]
            def call(t):
                n["v"]+=1; timeouts.append(t)
                if n["v"]==1: raise TransientError("temporary")
                return payload(activities=["cafe"])
            out=execute("홍대 카페",call,clock,cfg,cb,cache)
            assert out["runtime"]["source"]=="llm" and out["runtime"]["attempts"]==2 and n["v"]==2
            assert timeouts[0] <= 5.0 and timeouts[1] <= 8.0
        run_case("one_retry_then_success", c2, results)

        def c3():
            clock,cfg,cb,cache=fresh(); n={"v":0}
            def call(t): n["v"]+=1; raise NonRetryableError("bad request")
            out=execute("카페 가고 싶어",call,clock,cfg,cb,cache,retryable=lambda e:False)
            assert n["v"]==1 and out["runtime"]["source"]=="deterministic_fallback"
            assert out["intent"]["activities"]==["cafe"]
        run_case("nonretryable_immediate_fallback", c3, results)

        def c4():
            clock,cfg,cb,cache=fresh(); n={"v":0}
            def call(t): n["v"]+=1; raise TransientError("down")
            out=execute("카페 가고 싶어",call,clock,cfg,cb,cache)
            assert n["v"]==2 and out["runtime"]["source"]=="deterministic_fallback"
        run_case("two_failures_then_fallback", c4, results)

        def c5():
            clock,cfg,cb,cache=fresh()
            first=execute("홍대에서 카페 가고 싶어",lambda t:payload(activities=["cafe"]),clock,cfg,cb,cache)
            assert first["runtime"]["source"]=="llm"
            n={"v":0}
            def down(t): n["v"]+=1; raise TransientError("down")
            second=execute("홍대에서 카페 가고 싶어",down,clock,cfg,cb,cache)
            assert n["v"]==2 and second["runtime"]["source"]=="result_cache" and second["intent"]["activities"]==["cafe"]
        run_case("static_failure_uses_exact_result_cache", c5, results)

        def c6():
            assert not is_time_dependent_input("홍대에서 카페 가고 싶어")
            assert is_time_dependent_input("지금부터 두 시간 뭐할까?")
            assert is_time_dependent_input("2시간 뒤 강남 가야 해")
        run_case("time_dependency_detection", c6, results)

        def c7():
            clock,cfg,cb,cache=fresh()
            execute("지금부터 한두 시간 뭐할까?",lambda t:payload(desired_duration_min_minutes=60,desired_duration_max_minutes=120),clock,cfg,cb,cache)
            key=make_cache_key("지금부터 한두 시간 뭐할까?","gpt-5.6-luna")
            assert cache.get(key) is None
        run_case("relative_input_not_cached", c7, results)

        def c8():
            clock,cfg,cb,cache=fresh(); n={"v":0}
            def down(t): n["v"]+=1; raise TransientError("down")
            out=execute("지금부터 한두 시간 뭐할까?",down,clock,cfg,cb,cache)
            assert out["runtime"]["source"]=="deterministic_fallback"
            assert out["intent"]["end_time"] is None and out["intent"]["desired_duration_min_minutes"]==60 and out["intent"]["desired_duration_max_minutes"]==120
        run_case("relative_failure_uses_fallback_not_cache", c8, results)

        def c9():
            clock,cfg,cb,cache=fresh(threshold=2); n={"v":0}
            def down(t): n["v"]+=1; raise TransientError("down")
            out1=execute("첫 요청",down,clock,cfg,cb,cache)
            assert cb.snapshot()["state"]=="open"
            before=n["v"]
            out2=execute("두번째 요청",down,clock,cfg,cb,cache)
            assert n["v"]==before and out2["runtime"]["source"]=="deterministic_fallback"
        run_case("circuit_opens_and_bypasses_api", c9, results)

        def c10():
            clock,cfg,cb,cache=fresh(threshold=1)
            try: execute("a",lambda t:(_ for _ in ()).throw(TransientError("x")),clock,cfg,cb,cache)
            except Exception: pass
            assert cb.snapshot()["state"]=="open"
            clock.advance(31)
            out=execute("b",lambda t:payload(activities=["cafe"]),clock,cfg,cb,cache)
            assert out["runtime"]["source"]=="llm" and cb.snapshot()["state"]=="closed"
        run_case("half_open_probe_success_closes_circuit", c10, results)

        def c11():
            clock,cfg,cb,cache=fresh(ttl=60)
            key=make_cache_key("정적", "gpt-5.6-luna")
            cache.put(key, payload(activities=["cafe"])["intent"])
            assert cache.get(key) is not None
            clock.advance(61)
            assert cache.get(key) is None
        run_case("result_cache_ttl_expiry", c11, results)

        def c12():
            assert make_cache_key("abc","gpt-5.6-luna") != make_cache_key("abc","gpt-5.6-terra")
            assert make_cache_key("abc","gpt-5.6-luna","1.3.1") != make_cache_key("abc","gpt-5.6-luna","1.4")
        run_case("cache_isolated_by_model_and_parser_version", c12, results)

        def c13():
            out,_=deterministic_fallback("카페 가고 싶어",{})
            assert out["activities"]==["cafe"] and out["transport_mode"]=="auto"
        run_case("fallback_cafe", c13, results)

        def c14():
            out,_=deterministic_fallback("북촌에서 산책하고 싶어",{})
            assert out["activities"]==["walk"] and out["transport_mode"]=="auto"
        run_case("fallback_walk_activity_not_transport", c14, results)

        def c15():
            out,_=deterministic_fallback("걸어서 갈 만한 카페",{})
            assert out["transport_mode"]=="walk" and "cafe" in out["activities"]
        run_case("fallback_explicit_walk_transport", c15, results)

        def c16():
            out,_=deterministic_fallback("지하철 타고 카페 갈래",{})
            assert out["transport_mode"]=="public_transit"
        run_case("fallback_public_transport", c16, results)

        def c17():
            out,_=deterministic_fallback("차 가지고 왔고 밥 먹고 싶어",{})
            assert out["transport_mode"]=="car" and "food" in out["activities"]
        run_case("fallback_car", c17, results)

        def c18():
            out,_=deterministic_fallback("친구랑 카페 가고 싶어",{})
            assert out["companions"]==["friend"]
        run_case("fallback_current_friend", c18, results)

        def c19():
            out,_=deterministic_fallback("7시에 홍대에서 친구 만나야 해. 그 전에 카페 갈래",{})
            assert out["companions"]==[] and out["activities"]==["cafe"]
        run_case("fallback_future_friend_not_companion", c19, results)

        def c20():
            out,_=deterministic_fallback("오전에 북촌에서 산책하고 싶어",{})
            assert out["start_time_period"]=="am"
        run_case("fallback_literal_am", c20, results)

        def c21():
            out,_=deterministic_fallback("경복궁에서 구경하고 저녁쯤 광화문 가야 해",{})
            assert out["end_time_period"]=="evening" and "culture" not in out["activities"]
        run_case("fallback_end_evening_no_culture_hallucination", c21, results)

        def c22():
            out,_=deterministic_fallback("지금부터 한두 시간 뭐할까?",{})
            assert out["desired_duration_min_minutes"]==60 and out["desired_duration_max_minutes"]==120 and out["end_time"] is None
        run_case("fallback_compact_duration_range", c22, results)

        def c23():
            out,_=deterministic_fallback("야외에서 카페 가고 싶어",{})
            assert out["space_preference"]=="outdoor"
        run_case("fallback_space_preference", c23, results)

        def c24():
            out,_=deterministic_fallback("아무거나 추천",{})
            validate(out)
            assert set(out)==set(INTENT_DEFAULTS)
        run_case("fallback_always_16field_schema_valid", c24, results)

        def c25():
            clock,cfg,cb,cache=fresh()
            execute("정적 카페",lambda t:payload(activities=["cafe"]),clock,cfg,cb,cache)
            def down(t): raise TransientError("down")
            out=execute("정적 카페",down,clock,cfg,cb,cache)
            assert out["runtime"]["source"]=="result_cache"
            assert out["usage"]["total_tokens"]==0
        run_case("cache_fallback_consumes_zero_new_tokens", c25, results)

    passed=sum(1 for _,ok,_ in results if ok)
    failed=len(results)-passed
    for name,ok,msg in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {msg}" if msg else ""))
    print(json.dumps({"cases":len(results),"passed":passed,"failed":failed,"PASS":failed==0},ensure_ascii=False,indent=2))
    raise SystemExit(0 if failed==0 else 1)


if __name__ == "__main__":
    main()
