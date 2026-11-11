from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from evaluate_sa1_baselines import EvaluationConfig, evaluate_walk_forward


class BaselineEvaluationTests(unittest.TestCase):
    def test_walk_forward_is_chronological_and_returns_all_models(self) -> None:
        periods = 105 * 288
        time = pd.date_range("2025-01-01 00:05:00", periods=periods, freq="5min")
        seasonal = 70 + 20 * np.sin(np.arange(periods) * 2 * np.pi / 288)
        target = seasonal + np.sin(np.arange(periods) / 31)
        frame = pd.DataFrame({
            "TARGET_TIME_AEST": time,
            "PREDICTION_CUTOFF_AEST": time - pd.Timedelta(days=1),
            "TARGET_RRP": target,
            "RRP_LAG_288": pd.Series(target).shift(288),
            "RRP_LAG_576": pd.Series(target).shift(576),
            "RRP_LAG_2016": pd.Series(target).shift(2016),
            "RRP_ROLLING_MEDIAN_7D": pd.Series(target).shift(288).rolling(2016, min_periods=1008).median(),
            "CAL_TIME_SIN": np.sin(np.arange(periods) * 2 * np.pi / 288),
            "CAL_TIME_COS": np.cos(np.arange(periods) * 2 * np.pi / 288),
        })
        config = EvaluationConfig(
            min_train_days=35,
            train_window_days=60,
            max_train_rows=20_000,
            max_iter=8,
        )
        metrics, predictions, metadata = evaluate_walk_forward(frame, config)

        self.assertTrue(metadata["all_folds_chronology_valid"])
        self.assertGreater(len(metadata["folds"]), 0)
        self.assertFalse(predictions.empty)
        self.assertEqual(
            set(metrics.loc[metrics["fold"].eq("OVERALL"), "model"]),
            {"previous_day", "previous_week", "rolling_median_7d", "tree_baseline"},
        )
        for fold in metadata["folds"]:
            self.assertLess(pd.Timestamp(fold["train_end"]), pd.Timestamp(fold["test_start"]))

    def test_rejects_missing_weekly_baseline(self) -> None:
        time = pd.date_range("2025-01-01", periods=2_000, freq="5min")
        frame = pd.DataFrame({
            "TARGET_TIME_AEST": time,
            "PREDICTION_CUTOFF_AEST": time - pd.Timedelta(days=1),
            "TARGET_RRP": 50.0,
            "RRP_LAG_288": 50.0,
            "RRP_ROLLING_MEDIAN_7D": 50.0,
        })
        with self.assertRaisesRegex(ValueError, "previous_week"):
            evaluate_walk_forward(frame, EvaluationConfig(min_train_days=1))


if __name__ == "__main__":
    unittest.main()
