#!/usr/bin/env python3
"""Evaluate leakage-safe SA1 day-ahead price baselines with walk-forward splits."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline


TARGET = "TARGET_RRP"
TIME = "TARGET_TIME_AEST"
CUTOFF = "PREDICTION_CUTOFF_AEST"
BASELINE_COLUMNS = {
    "previous_day": "RRP_LAG_288",
    "previous_week": "RRP_LAG_2016",
    "rolling_median_7d": "RRP_ROLLING_MEDIAN_7D",
}


@dataclass(frozen=True)
class EvaluationConfig:
    min_train_days: int = 90
    train_window_days: int = 365
    max_train_rows: int = 120_000
    spike_threshold: float = 300.0
    max_iter: int = 150
    random_state: int = 42


def load_model_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    missing = {TIME, CUTOFF, TARGET}.difference(frame.columns)
    if missing:
        raise ValueError(f"Model table is missing required columns: {sorted(missing)}")
    frame[TIME] = pd.to_datetime(frame[TIME], errors="coerce")
    frame[CUTOFF] = pd.to_datetime(frame[CUTOFF], errors="coerce")
    frame[TARGET] = pd.to_numeric(frame[TARGET], errors="coerce")
    frame = frame.dropna(subset=[TIME, CUTOFF, TARGET]).sort_values(TIME)
    if frame[TIME].duplicated().any():
        raise ValueError("TARGET_TIME_AEST must be unique")
    if not frame[CUTOFF].lt(frame[TIME]).all():
        raise ValueError("Every prediction cutoff must be earlier than its target")
    return frame.reset_index(drop=True)


def _numeric_feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {TIME, CUTOFF, TARGET}
    columns = []
    for column in frame.columns:
        if column in excluded:
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.notna().any():
            frame[column] = converted
            columns.append(column)
    return columns


def _monthly_test_windows(frame: pd.DataFrame, min_train_days: int):
    first_allowed = frame[TIME].min() + pd.Timedelta(days=min_train_days)
    for period in frame.loc[frame[TIME].ge(first_allowed), TIME].dt.to_period("M").drop_duplicates():
        start = period.start_time
        end = (period + 1).start_time
        if frame[TIME].ge(start).any() and frame[TIME].lt(end).any():
            yield str(period), start, end


def _safe_training_columns(train: pd.DataFrame, candidates: list[str]) -> list[str]:
    selected = []
    for column in candidates:
        values = train[column]
        if values.notna().sum() >= 100 and values.nunique(dropna=True) > 1:
            selected.append(column)
    if not selected:
        raise ValueError("No usable numeric model features remain in the training window")
    return selected


def _metrics(actual: np.ndarray, predicted: np.ndarray, reference: np.ndarray, spike_threshold: float) -> dict[str, float | int]:
    valid = np.isfinite(actual) & np.isfinite(predicted)
    actual = actual[valid]
    predicted = predicted[valid]
    reference = reference[valid]
    if actual.size == 0:
        return {"n_obs": 0}

    error = predicted - actual
    direction_valid = np.isfinite(reference)
    if direction_valid.any():
        actual_direction = np.sign(actual[direction_valid] - reference[direction_valid])
        predicted_direction = np.sign(predicted[direction_valid] - reference[direction_valid])
        direction_accuracy = float(np.mean(actual_direction == predicted_direction))
    else:
        direction_accuracy = float("nan")

    actual_spike = np.abs(actual) >= spike_threshold
    predicted_spike = np.abs(predicted) >= spike_threshold
    tp = int(np.sum(actual_spike & predicted_spike))
    fp = int(np.sum(~actual_spike & predicted_spike))
    fn = int(np.sum(actual_spike & ~predicted_spike))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "n_obs": int(actual.size),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
        "median_ae": float(np.median(np.abs(error))),
        "bias": float(np.mean(error)),
        "direction_accuracy": direction_accuracy,
        "spike_precision": float(precision),
        "spike_recall": float(recall),
        "spike_f1": float(f1),
        "actual_spikes": int(actual_spike.sum()),
    }


def evaluate_walk_forward(frame: pd.DataFrame, config: EvaluationConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    frame = frame.copy()
    feature_candidates = _numeric_feature_columns(frame)
    missing_baselines = {name: column for name, column in BASELINE_COLUMNS.items() if column not in frame.columns}
    if missing_baselines:
        raise ValueError(f"Required baseline features are missing: {missing_baselines}")

    metrics_rows: list[dict] = []
    prediction_frames: list[pd.DataFrame] = []
    fold_metadata: list[dict] = []

    for fold, test_start, test_end in _monthly_test_windows(frame, config.min_train_days):
        train_start = test_start - pd.Timedelta(days=config.train_window_days)
        train = frame.loc[frame[TIME].lt(test_start) & frame[TIME].ge(train_start)].copy()
        test = frame.loc[frame[TIME].ge(test_start) & frame[TIME].lt(test_end)].copy()
        train = train.dropna(subset=[TARGET])
        if len(train) < 1_000 or test.empty:
            continue
        if len(train) > config.max_train_rows:
            train = train.tail(config.max_train_rows)

        selected = _safe_training_columns(train, feature_candidates)
        model = make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingRegressor(
                loss="absolute_error",
                learning_rate=0.06,
                max_iter=config.max_iter,
                max_leaf_nodes=31,
                min_samples_leaf=40,
                l2_regularization=1.0,
                random_state=config.random_state,
            ),
        )
        model.fit(train[selected], train[TARGET])

        predictions = pd.DataFrame({TIME: test[TIME], TARGET: test[TARGET], "FOLD": fold})
        for name, column in BASELINE_COLUMNS.items():
            predictions[name] = test[column].to_numpy()
        predictions["tree_baseline"] = model.predict(test[selected])
        reference = predictions["previous_day"].to_numpy(dtype=float)

        for model_name in [*BASELINE_COLUMNS, "tree_baseline"]:
            row = {"fold": fold, "model": model_name}
            row.update(
                _metrics(
                    predictions[TARGET].to_numpy(dtype=float),
                    predictions[model_name].to_numpy(dtype=float),
                    reference,
                    config.spike_threshold,
                )
            )
            metrics_rows.append(row)

        prediction_frames.append(predictions)
        fold_metadata.append({
            "fold": fold,
            "train_start": str(train[TIME].min()),
            "train_end": str(train[TIME].max()),
            "test_start": str(test[TIME].min()),
            "test_end": str(test[TIME].max()),
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
            "feature_count": len(selected),
            "chronology_valid": bool(train[TIME].max() < test[TIME].min()),
        })

    if not prediction_frames:
        raise ValueError("No valid walk-forward folds were produced; provide more history or lower --min-train-days")

    predictions = pd.concat(prediction_frames, ignore_index=True)
    fold_metrics = pd.DataFrame(metrics_rows)
    overall_rows = []
    reference = predictions["previous_day"].to_numpy(dtype=float)
    for model_name in [*BASELINE_COLUMNS, "tree_baseline"]:
        row = {"fold": "OVERALL", "model": model_name}
        row.update(
            _metrics(
                predictions[TARGET].to_numpy(dtype=float),
                predictions[model_name].to_numpy(dtype=float),
                reference,
                config.spike_threshold,
            )
        )
        overall_rows.append(row)
    metrics = pd.concat([fold_metrics, pd.DataFrame(overall_rows)], ignore_index=True)
    metadata = {
        "split_method": "monthly expanding walk-forward with a bounded training window",
        "config": config.__dict__,
        "folds": fold_metadata,
        "all_folds_chronology_valid": all(item["chronology_valid"] for item in fold_metadata),
    }
    return metrics, predictions, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data_sa1/model/sa1_day_ahead_features.csv.gz"))
    parser.add_argument("--output-dir", type=Path, default=Path("data_sa1/evaluation"))
    parser.add_argument("--min-train-days", type=int, default=90)
    parser.add_argument("--train-window-days", type=int, default=365)
    parser.add_argument("--max-train-rows", type=int, default=120_000)
    parser.add_argument("--spike-threshold", type=float, default=300.0)
    parser.add_argument("--max-iter", type=int, default=150)
    args = parser.parse_args()

    config = EvaluationConfig(
        min_train_days=args.min_train_days,
        train_window_days=args.train_window_days,
        max_train_rows=args.max_train_rows,
        spike_threshold=args.spike_threshold,
        max_iter=args.max_iter,
    )
    metrics, predictions, metadata = evaluate_walk_forward(load_model_table(args.input), config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.output_dir / "sa1_baseline_metrics.csv", index=False)
    predictions.to_csv(args.output_dir / "sa1_baseline_predictions.csv.gz", index=False, compression="gzip")
    (args.output_dir / "sa1_baseline_run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(metrics.loc[metrics["fold"].eq("OVERALL")].to_string(index=False))


if __name__ == "__main__":
    main()
