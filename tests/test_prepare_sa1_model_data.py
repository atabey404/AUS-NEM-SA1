from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from prepare_sa1_model_data import build_model_table


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, compression="gzip")


class PrepareModelDataTests(unittest.TestCase):
    def test_day_ahead_features_are_shifted_and_intervention_is_removed(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            periods = 2_500
            times = pd.date_range("2025-01-01 00:05:00", periods=periods, freq="5min")
            base = np.arange(periods, dtype=float)

            price = pd.DataFrame({"SETTLEMENTDATE": times, "REGIONID": "SA1", "RRP": base, "INTERVENTION": 0})
            duplicate = price.iloc[[500]].copy()
            duplicate["RRP"] = 999_999.0
            duplicate["INTERVENTION"] = 1
            _write(pd.concat([price, duplicate], ignore_index=True), tmp_path / "dispatch_price.csv.gz")

            region = pd.DataFrame({
                "SETTLEMENTDATE": times,
                "REGIONID": "SA1",
                "TOTALDEMAND": 1_000 + base,
                "AVAILABLEGENERATION": 2_000 + base,
                "INTERVENTION": 0,
            })
            _write(region, tmp_path / "dispatch_region_summary.csv.gz")

            inter = pd.concat([
                pd.DataFrame({"SETTLEMENTDATE": times, "INTERCONNECTORID": "V-SA", "MWFLOW": base, "INTERVENTION": 0}),
                pd.DataFrame({"SETTLEMENTDATE": times, "INTERCONNECTORID": "V-S-MNSP1", "MWFLOW": -base, "INTERVENTION": 0}),
            ], ignore_index=True)
            _write(inter, tmp_path / "dispatch_interconnector.csv.gz")

            model, qa = build_model_table(tmp_path, horizon=288)
            row = model.iloc[500]
            self.assertEqual(row["TARGET_RRP"], 500.0)
            self.assertEqual(row["RRP_LAG_288"], 212.0)
            self.assertEqual(row["REGION_TOTALDEMAND_LAG_288"], 1_212.0)
            self.assertEqual(row["PREDICTION_CUTOFF_AEST"], times[500] - pd.Timedelta(days=1))
            self.assertEqual(qa["forecast_horizon_hours"], 24)
            self.assertEqual(qa["target_missing"], 0)

    def test_weather_is_joined_to_target_time_without_using_reanalysis(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            periods = 2_500
            times = pd.date_range("2025-01-01 00:05:00", periods=periods, freq="5min")
            base = np.arange(periods, dtype=float)
            _write(pd.DataFrame({"SETTLEMENTDATE": times, "RRP": base}), tmp_path / "dispatch_price.csv.gz")
            _write(pd.DataFrame({"SETTLEMENTDATE": times, "TOTALDEMAND": 1_000 + base}), tmp_path / "dispatch_region_summary.csv.gz")
            _write(pd.DataFrame({"SETTLEMENTDATE": times, "INTERCONNECTORID": "V-SA", "MWFLOW": base}), tmp_path / "dispatch_interconnector.csv.gz")

            hourly = pd.date_range(times.min().floor("h"), times.max().ceil("h"), freq="h")
            weather = pd.DataFrame({
                "POINT_ID": "Adelaide",
                "TIME_AEST": hourly,
                "temperature_2m_previous_day1": np.arange(len(hourly), dtype=float),
            })
            _write(weather, tmp_path / "weather_day_ahead_previous_run_hourly.csv.gz")

            model, qa = build_model_table(tmp_path)
            self.assertIn("WEATHER_TEMPERATURE_2M_PREVIOUS_DAY1_MEAN", model.columns)
            self.assertTrue(qa["weather_features_included"])
            self.assertEqual(model.iloc[0]["WEATHER_TEMPERATURE_2M_PREVIOUS_DAY1_MEAN"], 0.0)
            self.assertEqual(model.iloc[10]["WEATHER_TEMPERATURE_2M_PREVIOUS_DAY1_MEAN"], 0.0)


if __name__ == "__main__":
    unittest.main()
