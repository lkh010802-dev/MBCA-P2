import copy

from intent_postprocess import postprocess_intent
from runtime_resilience import INTENT_DEFAULTS, PARSER_VERSION


def intent(**overrides):
    value = copy.deepcopy(INTENT_DEFAULTS)
    value.update(overrides)
    return value


CASES = [
    (
        "explicit_walk_and_park_stereotype",
        "여의도역에서 두 시간 정도 걸어서 공원 위주로 둘러보고 싶어.",
        intent(activities=["walk"], transport_mode="auto", space_preference="outdoor"),
        {"transport_mode": "walk", "space_preference": None},
    ),
    (
        "quiet_cafe_not_automatically_indoor",
        "조용한 카페에 가고 싶어.",
        intent(activities=["cafe"], space_preference="indoor"),
        {"space_preference": None},
    ),
    (
        "explicit_indoor_is_preserved",
        "조용한 실내 카페에 가고 싶어.",
        intent(activities=["cafe"], space_preference=None),
        {"space_preference": "indoor"},
    ),
    (
        "explicit_outdoor_is_preserved",
        "야외 공원 위주로 산책하고 싶어.",
        intent(activities=["walk"], space_preference=None),
        {"space_preference": "outdoor"},
    ),
    (
        "budget_phrase_is_not_indoor",
        "3만원 안에서 가성비 좋은 카페",
        intent(activities=["cafe"], budget_max=30000, space_preference=None),
        {"space_preference": None},
    ),
    (
        "inside_a_place_is_not_indoor_preference",
        "서울숲 안에서 좀 걷고 싶어",
        intent(activities=["walk"], space_preference=None),
        {"space_preference": None},
    ),
    (
        "limited_time_phrase_is_not_outdoor",
        "두 시간밖에 시간이 없어. 밥 먹고 싶어",
        intent(activities=["food"], space_preference=None),
        {"space_preference": None},
    ),
    (
        "corrected_space_preference_becomes_any",
        "실내가 좋긴 한데 아냐 밖도 상관없어",
        intent(space_preference="indoor"),
        {"space_preference": "any"},
    ),
    (
        "walking_activity_is_not_transport",
        "여의도 공원에서 두 시간 산책하고 싶어.",
        intent(activities=["walk"], transport_mode="walk"),
        {"transport_mode": "auto"},
    ),
    (
        "negated_walk_is_not_recovered",
        "걸어서 말고 대중교통으로 가고 싶어.",
        intent(transport_mode="auto"),
        {"transport_mode": "auto"},
    ),
    (
        "other_transport_is_not_overwritten",
        "지하철로 가서 공원을 걸어 보고 싶어.",
        intent(activities=["walk"], transport_mode="public_transit"),
        {"transport_mode": "public_transit"},
    ),
]


def main():
    assert PARSER_VERSION == "1.4.1-start-location-priority"
    failures = []
    for name, text, predicted, expected in CASES:
        actual, changes = postprocess_intent(text, {}, predicted)
        mismatch = {
            field: {"expected": value, "actual": actual.get(field)}
            for field, value in expected.items()
            if actual.get(field) != value
        }
        if mismatch:
            failures.append((name, mismatch, changes))
            print(f"[FAIL] {name}: {mismatch} changes={changes}")
        else:
            print(f"[PASS] {name}")
    print(f"policy fixes: {len(CASES) - len(failures)}/{len(CASES)} PASS")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
