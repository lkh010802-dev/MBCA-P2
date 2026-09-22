from personalization_service import day_part, merge_behavior_preferences


def test_day_part_keeps_time_contexts_separate():
    assert day_part(9) == "morning"
    assert day_part(13) == "lunch"
    assert day_part(19) == "evening"


def test_explicit_preference_wins_over_behavior(monkeypatch):
    monkeypatch.setattr(
        "personalization_service.current_context_key",
        lambda: "weekday:evening",
    )
    profile = {
        "activity_preferences": {"cafe": 4, "walk": 4},
        "context_activity_preferences": {
            "weekday:evening": {"food": 5, "cafe": 5},
        },
    }
    merged = merge_behavior_preferences({"cafe": 2}, profile)

    assert merged["cafe"] == 2
    assert merged["food"] == 5
    assert merged["walk"] == 4

