"""Standalone inference for the exported D-4 Direct LightGBM artifacts."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEPS = HERE.parents[1] / "experiments" / "d4_gap_test" / ".deps"
if DEPS.exists():
    sys.path.insert(0, str(DEPS))

import joblib
import numpy as np
import pandas as pd


FEATURES = [
    "dong", "target_hour", "target_dow", "target_month", "target_weekend",
    "target_hour_sin", "target_hour_cos", "target_dow_sin", "target_dow_cos",
    "issue_lag_96_ratio", "issue_lag_168_ratio", "issue_lag_336_ratio",
    "stale_change_96_168", "stale_change_168_336",
]
LAGS = (96, 168, 336)
REQUIRED_COLUMNS = {"datetime", "행정동코드", "생활인구합계"}


class D4InferenceError(RuntimeError):
    code = "inference_failure"


class UnsupportedRegionError(D4InferenceError):
    code = "unsupported_region"


class InsufficientHistoryError(D4InferenceError):
    code = "insufficient_history"


class PopulationSourceError(D4InferenceError):
    code = "population_source_failure"


class D4DirectPredictor:
    """Loads six D-4 models; service allowlists intentionally remain external."""

    def __init__(self, artifact_dir: str | Path = HERE) -> None:
        artifact_dir = Path(artifact_dir)
        metadata = joblib.load(artifact_dir / "d4_direct_metadata.joblib")
        if metadata["features"] != FEATURES:
            raise D4InferenceError("Artifact feature order does not match D-4 Direct")
        self.baseline = {int(code): float(value) for code, value in metadata["baseline"].items()}
        self.categories = np.asarray(metadata["categorical_dong_codes"], dtype="int32")
        if len(self.categories) != 428:
            raise D4InferenceError(f"Expected 428 model categories, got {len(self.categories)}")
        self.models = {h: joblib.load(artifact_dir / f"d4_direct_h{h}.joblib") for h in range(1, 7)}
        for horizon, model in self.models.items():
            if list(model.feature_name_) != FEATURES:
                raise D4InferenceError(f"Feature-order mismatch in horizon {horizon}")

    def _features(self, issue_time: object, dong_code: int, population: pd.DataFrame) -> pd.DataFrame:
        try:
            issue_time = pd.Timestamp(issue_time)
            dong_code = int(dong_code)
        except Exception as exc:
            raise PopulationSourceError("Invalid issue time or LOCAL_RESD code") from exc
        if dong_code not in self.baseline:
            raise UnsupportedRegionError(f"LOCAL_RESD code is not a model category: {dong_code}")
        if not isinstance(population, pd.DataFrame) or not REQUIRED_COLUMNS.issubset(population.columns):
            raise PopulationSourceError(f"Required columns: {sorted(REQUIRED_COLUMNS)}")

        values = population.loc[:, ["datetime", "행정동코드", "생활인구합계"]].copy()
        try:
            values["datetime"] = pd.to_datetime(values["datetime"])
            values["행정동코드"] = values["행정동코드"].astype("int32")
            values["생활인구합계"] = values["생활인구합계"].astype("float32")
        except Exception as exc:
            raise PopulationSourceError("Population source has invalid values") from exc
        required_times = [issue_time - pd.Timedelta(hours=lag) for lag in LAGS]
        rows = values[(values["행정동코드"] == dong_code) & values["datetime"].isin(required_times)]
        if rows.duplicated("datetime").any():
            raise PopulationSourceError("Population source has duplicate datetime/dong rows")
        population_by_time = rows.set_index("datetime")["생활인구합계"]
        missing = [at.isoformat() for at in required_times if at not in population_by_time.index]
        if missing:
            raise InsufficientHistoryError(f"Missing D-4 history: {', '.join(missing)}")

        ratios = {lag: np.float32(population_by_time[issue_time - pd.Timedelta(hours=lag)] / self.baseline[dong_code]) for lag in LAGS}
        frame = pd.DataFrame({
            "dong": pd.Categorical([dong_code], categories=self.categories),
            "issue_lag_96_ratio": [ratios[96]],
            "issue_lag_168_ratio": [ratios[168]],
            "issue_lag_336_ratio": [ratios[336]],
            "stale_change_96_168": [np.float32(ratios[96] - ratios[168])],
            "stale_change_168_336": [np.float32(ratios[168] - ratios[336])],
        })
        return frame, issue_time

    @staticmethod
    def _add_calendar(frame: pd.DataFrame, issue_time: pd.Timestamp, horizon: int) -> None:
        target = issue_time + pd.Timedelta(hours=horizon)
        hour, dow = target.hour, target.dayofweek
        frame["target_hour"] = np.int8(hour)
        frame["target_dow"] = np.int8(dow)
        frame["target_month"] = np.int8(target.month)
        frame["target_weekend"] = np.int8(dow >= 5)
        frame["target_hour_sin"] = np.float32(np.sin(2 * np.pi * hour / 24))
        frame["target_hour_cos"] = np.float32(np.cos(2 * np.pi * hour / 24))
        frame["target_dow_sin"] = np.float32(np.sin(2 * np.pi * dow / 7))
        frame["target_dow_cos"] = np.float32(np.cos(2 * np.pi * dow / 7))

    def predict(self, issue_time: object, dong_code: int, population: pd.DataFrame) -> dict:
        base, issue_time = self._features(issue_time, dong_code, population)
        forecasts = []
        for horizon, model in self.models.items():
            feature_frame = base.copy()
            self._add_calendar(feature_frame, issue_time, horizon)
            probabilities = np.zeros(4, dtype="float64")
            probabilities[model.classes_.astype(int)] = model.predict_proba(feature_frame[FEATURES])[0]
            forecasts.append({
                "horizon_hours": horizon,
                "p0": float(probabilities[0]), "p1": float(probabilities[1]),
                "p2": float(probabilities[2]), "p3": float(probabilities[3]),
                "relative_congestion_index": float(np.dot(np.arange(4), probabilities)),
            })
        return {"status": "ok", "issue_time": issue_time.isoformat(), "local_resd_code": int(dong_code), "forecasts": forecasts}

    def predict_from_loader(self, issue_time: object, dong_code: int, loader: Callable[[], pd.DataFrame]) -> dict:
        try:
            population = loader()
        except Exception as exc:
            raise PopulationSourceError("Population source load failed") from exc
        return self.predict(issue_time, dong_code, population)

    def predict_safe(self, issue_time: object, dong_code: int, population: pd.DataFrame) -> dict:
        try:
            return self.predict(issue_time, dong_code, population)
        except D4InferenceError as exc:
            return {"status": exc.code, "detail": str(exc)}
        except Exception:
            return {"status": "inference_failure", "detail": "Unexpected D-4 inference failure"}
