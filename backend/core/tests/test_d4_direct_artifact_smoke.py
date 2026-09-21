from local_resd_congestion_adapter import (
    DEFAULT_D4_DIRECT_ARTIFACT_DIR,
    D4DirectCongestionAdapter,
    _load_configured_provider,
)


REQUIRED_ARTIFACT_FILES = {
    "d4_direct_provider.py",
    "standalone_inference.py",
    "local_resd_support_master.csv",
    "d4_direct_metadata.joblib",
    *(f"d4_direct_h{horizon}.joblib" for horizon in range(1, 7)),
}


def test_bundled_d4_direct_artifact_loads_without_external_desktop_path(monkeypatch):
    monkeypatch.delenv("D4_DIRECT_ARTIFACT_DIR", raising=False)
    assert {path.name for path in DEFAULT_D4_DIRECT_ARTIFACT_DIR.iterdir()} >= REQUIRED_ARTIFACT_FILES

    _load_configured_provider.cache_clear()
    provider = D4DirectCongestionAdapter()._provider_or_fallback()

    assert provider is not None
    assert len(provider.service_allowlist) == 427
