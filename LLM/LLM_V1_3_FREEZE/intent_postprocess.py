#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Conservative deterministic normalization after the LLM parser.
V1.3 candidate: FIX6 rules + safe target/scope consistency normalization.
"""

import copy
import re
from datetime import datetime, timedelta

KOREAN_HOURS = {
    "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5,
    "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}

_DURATION_CORE = (
    r"(?:\d+\s*시간(?:\s*(?:반|\d+\s*분))?|\d+\s*분|"
    r"(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*시간(?:\s*반)?)"
)

# Exact relative availability only. Intentionally does NOT match "있고 싶어".
_AVAILABILITY_RE = re.compile(
    rf"(?P<duration>{_DURATION_CORE})\s*(?:정도\s*)?(?:시간\s*)?"
    r"(?P<cue>있어|있다|있음|있는데|비어|비었어|비었다|비는데|여유\s*있어|여유\s*있다)"
)

_DURATION_MENTION_RE = re.compile(_DURATION_CORE)

_EXPLICIT_WALK_TRANSPORT_RE = re.compile(
    r"걸어서|도보(?:로)?|걸어\s*(?:가|갈|이동)|걷(?:는|기)\s*거리"
)
_ACTIVITY_WALK_RE = re.compile(r"걷|산책")

# Conservative friend cues used to suppress a specific friend hallucination.
_FRIEND_CUE_RE = re.compile(r"친구|친구들|지인|동기|친한\s*사람")

# A person mentioned only as a later appointment before "그 전에" is not a current companion.
_NEXT_SCHEDULE_PERSON_BEFORE_RE = re.compile(
    r"(?P<person>친구|여자친구|남자친구|여친|남친|애인|연인|가족|엄마|아빠|부모님|아이|아기|자녀|회사\s*동료|직장\s*동료|동료)"
    r".{0,24}?(?:만나야\s*해|만날\s*거|만나기로|약속(?:이|\s*있)|보기로)"
    r".{0,24}?그\s*전에"
)

_PERIOD_WORD_TO_ENUM = {
    "아침": "morning", "점심": "lunch", "저녁": "evening", "오전": "am", "오후": "pm",
}
_PERIOD_MARK_CAPTURE_RE = re.compile(r"(?P<word>아침|점심|저녁|오전|오후)\s*(?:쯤|에|시간대에)")
_NEXT_SCHEDULE_CUE_RE = re.compile(r"가야\s*해|가야\s*돼|약속(?:이|\s*있)|만나야\s*해|다음\s*일정|일정(?:이|\s*있)")

# Important: do not start a single-number match in the middle of Korean ranges
# such as "한두 시간" -> accidentally matching "두 시간".
_OPEN_ENDED_DURATION_RE = re.compile(
    r"(?:지금부터\s*|앞으로\s*)"
    r"(?<![한두세네])"
    rf"(?P<duration>{_DURATION_CORE})"
    r"\s*(?:정도\s*|동안\s*)?(?:그냥\s*)?"
    r"(?P<cue>뭐\s*하지|뭘\s*하지|뭐\s*할까|뭘\s*할까|놀고\s*싶어|시간\s*보내고\s*싶어)"
)


def _duration_text_to_minutes(text: str):
    s = re.sub(r"\s+", " ", text.strip())

    m = re.fullmatch(r"(\d+)\s*분", s)
    if m:
        return int(m.group(1))

    m = re.fullmatch(r"(\d+)\s*시간(?:\s*(반|(\d+)\s*분))?", s)
    if m:
        minutes = int(m.group(1)) * 60
        if m.group(2) == "반":
            minutes += 30
        elif m.group(3):
            minutes += int(m.group(3))
        return minutes

    m = re.fullmatch(
        r"(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*시간(?:\s*(반))?", s
    )
    if m:
        minutes = KOREAN_HOURS[m.group(1)] * 60
        if m.group(2) == "반":
            minutes += 30
        return minutes

    return None


def _clock_plus_minutes(start_hhmm: str, minutes: int):
    try:
        hh, mm = map(int, start_hhmm.split(":"))
        total = (hh * 60 + mm + minutes) % (24 * 60)
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return None


def _current_clock_plus_minutes(context: dict, minutes: int):
    raw = (context or {}).get("current_datetime")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        out = dt + timedelta(minutes=minutes)
        return out.strftime("%H:%M")
    except Exception:
        return None


def postprocess_intent(user_input: str, runtime_context: dict, predicted: dict):
    """Return (normalized_prediction, changes)."""
    if not isinstance(predicted, dict):
        return predicted, []

    out = copy.deepcopy(predicted)
    changes = []

    # Rule A: "N시간 시간 있어/비어/여유 있어" is availability, not desired duration.
    match = _AVAILABILITY_RE.search(user_input)
    if match:
        minutes = _duration_text_to_minutes(match.group("duration"))
        if minutes is not None:
            computed_end = None
            if out.get("start_time"):
                computed_end = _clock_plus_minutes(out["start_time"], minutes)
            if computed_end is None:
                computed_end = _current_clock_plus_minutes(runtime_context, minutes)

            if computed_end is not None and out.get("end_time") != computed_end:
                changes.append({"field":"end_time","from":out.get("end_time"),"to":computed_end,
                                "reason":"explicit_relative_availability"})
                out["end_time"] = computed_end

            if computed_end is not None and out.get("end_time_period") is not None:
                changes.append({"field":"end_time_period","from":out.get("end_time_period"),"to":None,
                                "reason":"exact_end_time_precedence"})
                out["end_time_period"] = None

            # Preserve a separate desired duration if the sentence contains >=2 durations.
            if len(_DURATION_MENTION_RE.findall(user_input)) == 1:
                for field in ("desired_duration_min_minutes", "desired_duration_max_minutes"):
                    if out.get(field) is not None:
                        changes.append({"field":field,"from":out.get(field),"to":None,
                                        "reason":"availability_not_desired_duration"})
                        out[field] = None

    # Rule C: relative open-ended "지금부터/앞으로 N시간 뭐하지/뭐 할까" is desired duration,
    # not an availability endpoint. Korean ranges such as 한두/두세 are deliberately
    # NOT rewritten here; the LLM output is preserved for those.
    open_match = _OPEN_ENDED_DURATION_RE.search(user_input)
    if open_match and not _AVAILABILITY_RE.search(user_input):
        minutes = _duration_text_to_minutes(open_match.group("duration"))
        if minutes is not None:
            if out.get("end_time") is not None:
                changes.append({"field":"end_time","from":out.get("end_time"),"to":None,
                                "reason":"open_ended_duration_not_availability"})
                out["end_time"] = None

            if out.get("end_time_period") is not None:
                changes.append({"field":"end_time_period","from":out.get("end_time_period"),"to":None,
                                "reason":"open_ended_duration_not_availability"})
                out["end_time_period"] = None

            for field in ("desired_duration_min_minutes", "desired_duration_max_minutes"):
                if out.get(field) != minutes:
                    changes.append({"field":field,"from":out.get(field),"to":minutes,
                                    "reason":"open_ended_desired_duration"})
                    out[field] = minutes


    # Rule E1: suppress a friend hallucination only when the text has no friend cue at all.
    # Keep this category-specific to avoid deleting valid family/partner synonyms.
    if "friend" in (out.get("companions") or []) and not _FRIEND_CUE_RE.search(user_input):
        new_companions = [x for x in out.get("companions", []) if x != "friend"]
        changes.append({"field":"companions","from":out.get("companions"),"to":new_companions,
                        "reason":"friend_without_friend_cue"})
        out["companions"] = new_companions

    # Rule E2: a person in a later appointment before "그 전에" is not a companion
    # of the current recommendation activity. Keep this rule deliberately narrow.
    if out.get("companions") and _NEXT_SCHEDULE_PERSON_BEFORE_RE.search(user_input):
        after = re.split(r"그\s*전에", user_input, maxsplit=1)[-1]
        # If the current-activity clause does not explicitly mention a companion noun,
        # the appointment person belongs to the later schedule, not the current activity.
        current_companion_cue = re.search(
            r"혼자|친구|여자친구|남자친구|여친|남친|애인|연인|가족|엄마|아빠|부모님|아이|아기|자녀|회사\s*동료|직장\s*동료|동료",
            after,
        )
        if not current_companion_cue:
            changes.append({"field":"companions","from":out.get("companions"),"to":[],
                            "reason":"later_appointment_person_not_current_companion"})
            out["companions"] = []

    # Rule F: a marked life-period closest to a later-schedule cue belongs to end_time_period.
    # Choosing the closest preceding period avoids stealing an earlier start period, e.g.
    # "오전에 성수 ... 저녁쯤 강남 가야 해" -> start=am, end=evening.
    if out.get("end_time") is None:
        selected = None
        for cue in _NEXT_SCHEDULE_CUE_RE.finditer(user_input):
            periods = [m for m in _PERIOD_MARK_CAPTURE_RE.finditer(user_input, 0, cue.start())
                       if cue.start() - m.end() <= 48]
            if periods:
                selected = periods[-1]
                break
        if selected is not None:
            enum = _PERIOD_WORD_TO_ENUM[selected.group("word")]
            if out.get("end_time_period") != enum:
                changes.append({"field":"end_time_period","from":out.get("end_time_period"),"to":enum,
                                "reason":"period_modifies_next_schedule"})
                out["end_time_period"] = enum
            # Clear a swapped start period only when there is a single marked period total.
            if len(list(_PERIOD_MARK_CAPTURE_RE.finditer(user_input))) == 1 and out.get("start_time_period") == enum:
                changes.append({"field":"start_time_period","from":out.get("start_time_period"),"to":None,
                                "reason":"single_period_belongs_to_end_endpoint"})
                out["start_time_period"] = None

    # Rule D: scope cannot exist without a target location.
    # Do not infer area/place here; semantic classification remains an LLM task.
    if out.get("target_location_text") is None and out.get("target_location_scope") is not None:
        changes.append({"field":"target_location_scope","from":out.get("target_location_scope"),"to":None,
                        "reason":"target_scope_requires_target_location"})
        out["target_location_scope"] = None

    # Rule B: walking as an activity is not automatically a transport constraint.
    if (
        out.get("transport_mode") == "walk"
        and _ACTIVITY_WALK_RE.search(user_input)
        and not _EXPLICIT_WALK_TRANSPORT_RE.search(user_input)
    ):
        changes.append({"field":"transport_mode","from":"walk","to":"auto",
                        "reason":"walking_activity_not_transport"})
        out["transport_mode"] = "auto"

    return out, changes
