import activity_score
import local_resd_candidates
from poi import load_poi_candidates


def test_default_recommendation_loaders_ignore_working_directory(monkeypatch, tmp_path):
    activity_score._load_poi_activity_scores_cached.cache_clear()
    local_resd_candidates._load_local_resd_candidates_cached.cache_clear()
    monkeypatch.chdir(tmp_path)

    assert len(load_poi_candidates()) == 121
    assert len(activity_score.load_poi_activity_scores()) == 121
    assert len(local_resd_candidates.load_local_resd_candidates()) == 421
