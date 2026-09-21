"""Thin service boundary for D-4 Direct standalone inference."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from standalone_inference import D4DirectPredictor


HERE = Path(__file__).resolve().parent
DEFAULT_SUPPORT_MASTER = HERE / "local_resd_support_master.csv"
MODEL_NAME = "d4_direct_lightgbm_1to6h"
MODEL_VERSION = "d4_direct_artifact_v1"


class D4DirectProvider:
    """Applies the separate 427-code service allowlist, then delegates inference."""

    def __init__(self, artifact_dir: str | Path = HERE, support_master: str | Path = DEFAULT_SUPPORT_MASTER) -> None:
        support = pd.read_csv(support_master, usecols=["LOCAL_RESD_CODE"])
        self.service_allowlist = frozenset(support["LOCAL_RESD_CODE"].astype("int32"))
        if len(self.service_allowlist) != 427:
            raise RuntimeError(f"Expected 427 service support codes, got {len(self.service_allowlist)}")
        self.predictor = D4DirectPredictor(artifact_dir)

    @staticmethod
    def _contract(status: str, local_resd: object, issue_time: object, **extra: object) -> dict:
        return {
            "status": status,
            "model": {"name": MODEL_NAME, "version": MODEL_VERSION},
            "LOCAL_RESD": local_resd,
            "issue_time": str(issue_time),
            **extra,
        }

    def predict(self, local_resd: int, issue_time: object, population: pd.DataFrame) -> dict:
        try:
            local_resd = int(local_resd)
        except (TypeError, ValueError):
            return self._contract("unsupported_region", local_resd, issue_time)
        if local_resd not in self.service_allowlist:
            return self._contract("unsupported_region", local_resd, issue_time)

        result = self.predictor.predict_safe(issue_time, local_resd, population)
        if result["status"] != "ok":
            return self._contract(result["status"], local_resd, issue_time, detail=result.get("detail"))
        return self._contract(
            "ok", local_resd, result["issue_time"], forecasts=result["forecasts"],
        )
