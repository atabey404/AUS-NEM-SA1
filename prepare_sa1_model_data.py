#!/usr/bin/env python3
"""Build a leakage-controlled SA1 day-ahead price modelling table.

Each output row represents one five-minute target interval. Realised market
features are shifted by at least the forecast horizon (288 intervals by
default), while archived fixed-lead weather forecasts are joined directly to
their target interval. The realised SA1 RRP is retained only as the label.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd


TIMESTAMP_CANDIDATES = ("SETTLEMENTDATE", "INTERVAL_DATETIME", "DATETIME", "TIME_AEST")
PRICE_FILE = "dispatch_price.csv.gz"
REGION_FILE = "dispatch_region_summary.csv.gz"
INTERCONNECTOR_FILE = "dispatch_interconnector.csv.gz"
DEMAND_FILE = "operational_demand_actual.csv.gz"
WEATHER_FILE = "weather_day_ahead_previous_run_hourly.csv.gz"


def _clean_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required input is missing: {path}")
    frame = pd.read_csv(path, low_memory=False)
    frame.columns = [_clean_name(str(column)) for column in frame.columns]
    return frame


def _timestamp_column(frame: pd.DataFrame) -> str:
    for candidate in TIMESTAMP_CANDIDATES:
        if candidate in frame.columns:
            return candidate
    raise ValueError(f"No supported timestamp column found. Columns: {list(frame.columns)}")


def _index_market_table(frame: pd.DataFrame) -> pd.DataFrame:
    if "INTERVENTION" in frame.columns:
        intervention = pd.to_numeric(frame["INTERVENTION"], errors="coerce").fillna(0)
        frame = frame.loc[intervention.eq(0)].copy()
    timestamp = _timestamp_column(frame)
    frame["TARGET_TIME_AEST"] = pd.to_datetime(frame[timestamp], errors="coerce")
    frame = frame.dropna(subset=["TARGET_TIME_AEST"])
    return frame.sort_values("TARGET_TIME_AEST")


def _numeric_columns(frame: pd.DataFrame, excluded: set[str]) -> list[str]:
    selected: list[str] = []
    for column in frame.columns:
        if column in excluded:
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.notna().any():
            frame[column] = converted
            selected.append(column)
    return selected


def load_price(data_dir: Path) -> pd.DataFrame:
    frame = _index_market_table(_read(data_dir / PRICE_FILE))
    if "RRP" not in frame.columns:
        raise ValueError("DISPATCHPRICE input does not contain RRP")
    frame["RRP"] = pd.to_numeric(frame["RRP"], errors="coerce")
    return (
        frame.dropna(subset=["RRP"])
        .drop_duplicates("TARGET_TIME_AEST", keep="last")
        .set_index("TARGET_TIME_AEST")[["RRP"]]
        .rename(columns={"RRP": "TARGET_RRP"})
    )


def load_region_summary(data_dir: Path) -> pd.DataFrame:
    frame = _index_market_table(_read(data_dir / REGION_FILE))
    excluded = {
        _timestamp_column(frame), "TARGET_TIME_AEST", "REGIONID", "INTERVENTION",
        "RUNNO", "VERSIONNO", "LASTCHANGED", "PUBLISH_DATETIME",
    }
    preferred = [
        "TOTALDEMAND",
        "DEMANDFORECAST",
        "DISPATCHABLEGENERATION",
        "DISPATCHABLELOAD",
        "NETINTERCHANGE",
        "AVAILABLEGENERATION",
        "AVAILABLELOAD",
        "TOTALINTERMITTENTGENERATION",
        "UIGF",
        "SEMISCHEDULE_CLEAREDMW",
    ]
    columns = [column for column in preferred if column in frame.columns]
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if not columns:
        # Retain a bounded fallback for older or renamed data-model versions.
        columns = _numeric_columns(frame, excluded)[:20]
    if not columns:
        raise ValueError("No numeric fields found in DISPATCHREGIONSUM")
    result = frame.drop_duplicates("TARGET_TIME_AEST", keep="last").set_index("TARGET_TIME_AEST")[columns]
    return result.add_prefix("REGION_")


def load_interconnectors(data_dir: Path) -> pd.DataFrame:
    frame = _index_market_table(_read(data_dir / INTERCONNECTOR_FILE))
    if "INTERCONNECTORID" not in frame.columns:
        raise ValueError("Interconnector input does not contain INTERCONNECTORID")
    preferred = ["MWFLOW", "METEREDMWFLOW", "MWLOSSES", "EXPORTLIMIT", "IMPORTLIMIT"]
    values = [column for column in preferred if column in frame.columns]
    if not values:
        excluded = {_timestamp_column(frame), "TARGET_TIME_AEST", "INTERCONNECTORID", "INTERVENTION"}
        values = _numeric_columns(frame, excluded)
    for column in values:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    pivot = frame.pivot_table(
        index="TARGET_TIME_AEST", columns="INTERCONNECTORID", values=values, aggfunc="last"
    )
    pivot.columns = [f"INTER_{_clean_name(str(interconnector))}_{_clean_name(str(field))}" for field, interconnector in pivot.columns]
    return pivot.sort_index()


def load_optional_demand(data_dir: Path) -> pd.DataFrame | None:
    path = data_dir / DEMAND_FILE
    if not path.exists():
        return None
    frame = _index_market_table(_read(path))
    demand_columns = [column for column in ("OPERATIONAL_DEMAND", "OPERATIONAL_DEMAND_ADJUSTMENT", "WDR_ESTIMATE") if column in frame.columns]
    if not demand_columns:
        return None
    for column in demand_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.drop_duplicates("TARGET_TIME_AEST", keep="last")
        .set_index("TARGET_TIME_AEST")[demand_columns]
        .add_prefix("DEMAND_")
        .sort_index()
    )


def load_optional_weather(data_dir: Path, target_index: pd.DatetimeIndex) -> pd.DataFrame | None:
    path = data_dir / WEATHER_FILE
    if not path.exists():
        return None
    frame = _read(path)
    timestamp = _timestamp_column(frame)
    frame["TARGET_TIME_AEST"] = pd.to_datetime(frame[timestamp], errors="coerce")
    frame = frame.dropna(subset=["TARGET_TIME_AEST"])
    excluded = {timestamp, "TARGET_TIME_AEST", "POINT_ID", "LATITUDE", "LONGITUDE", "POINT_ROLE"}
    variables = _numeric_columns(frame, excluded)
    if not variables:
        return None
    grouped = frame.groupby("TARGET_TIME_AEST")[variables].agg(["mean", "min", "max"])
    grouped.columns = [f"WEATHER_{_clean_name(variable)}_{stat.upper()}" for variable, stat in grouped.columns]
    # Forecasts are hourly. Preserve the exact hourly observations before
    # expanding them across the following eleven five-minute timestamps.
    expanded_index = grouped.index.union(target_index)
    return grouped.reindex(expanded_index).sort_index().ffill(limit=11).reindex(target_index)


def add_calendar_features(frame: pd.DataFrame) -> None:
    minute_of_day = frame.index.hour * 60 + frame.index.minute
    frame["CAL_TIME_SIN"] = np.sin(2 * math.pi * minute_of_day / 1440)
    frame["CAL_TIME_COS"] = np.cos(2 * math.pi * minute_of_day / 1440)
    frame["CAL_DOW_SIN"] = np.sin(2 * math.pi * frame.index.dayofweek / 7)
    frame["CAL_DOW_COS"] = np.cos(2 * math.pi * frame.index.dayofweek / 7)
    frame["CAL_MONTH_SIN"] = np.sin(2 * math.pi * (frame.index.month - 1) / 12)
    frame["CAL_MONTH_COS"] = np.cos(2 * math.pi * (frame.index.month - 1) / 12)


def build_model_table(data_dir: Path, horizon: int = 288) -> tuple[pd.DataFrame, dict]:
    if horizon < 1:
        raise ValueError("horizon must be at least one interval")

    price = load_price(data_dir)
    observed = price.rename(columns={"TARGET_RRP": "RRP"}).join(load_region_summary(data_dir), how="left")
    observed = observed.join(load_interconnectors(data_dir), how="left")

    demand = load_optional_demand(data_dir)
    if demand is not None:
        observed = observed.join(demand.reindex(observed.index).ffill(limit=5), how="left")

    model = pd.DataFrame(index=observed.index)
    model["TARGET_RRP"] = price["TARGET_RRP"]
    model["PREDICTION_CUTOFF_AEST"] = model.index - pd.to_timedelta(horizon * 5, unit="minute")

    lag_steps = sorted(set([horizon, horizon * 2, max(horizon, 2016)]))
    numeric = observed.select_dtypes(include=[np.number])
    for column in numeric.columns:
        for lag in lag_steps:
            model[f"{column}_LAG_{lag}"] = numeric[column].shift(lag)
        model[f"{column}_ROLLING_MEAN_1D"] = numeric[column].shift(horizon).rolling(288, min_periods=144).mean()
        model[f"{column}_ROLLING_STD_1D"] = numeric[column].shift(horizon).rolling(288, min_periods=144).std()
        model[f"{column}_ROLLING_MEAN_7D"] = numeric[column].shift(horizon).rolling(2016, min_periods=1008).mean()
        if column == "RRP":
            model["RRP_ROLLING_MEDIAN_7D"] = numeric[column].shift(horizon).rolling(2016, min_periods=1008).median()

    add_calendar_features(model)
    weather = load_optional_weather(data_dir, model.index)
    if weather is not None:
        model = model.join(weather, how="left")

    model.index.name = "TARGET_TIME_AEST"
    model = model.reset_index()
    feature_columns = [column for column in model.columns if column not in {"TARGET_TIME_AEST", "PREDICTION_CUTOFF_AEST", "TARGET_RRP"}]
    qa = {
        "forecast_horizon_intervals": horizon,
        "forecast_horizon_hours": horizon * 5 / 60,
        "rows": int(len(model)),
        "first_target": str(model["TARGET_TIME_AEST"].min()),
        "last_target": str(model["TARGET_TIME_AEST"].max()),
        "feature_count": len(feature_columns),
        "weather_features_included": bool(weather is not None),
        "operational_demand_included": bool(demand is not None),
        "complete_feature_rows": int(model[feature_columns].notna().all(axis=1).sum()),
        "target_missing": int(model["TARGET_RRP"].isna().sum()),
        "leakage_rule": "Realised market features use lags greater than or equal to the forecast horizon.",
    }
    return model, qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data_sa1"), help="Directory created by download_sa1_nem_data.py")
    parser.add_argument("--output", type=Path, default=Path("data_sa1/model/sa1_day_ahead_features.csv.gz"))
    parser.add_argument("--qa-output", type=Path, default=Path("data_sa1/model/sa1_day_ahead_features_qa.json"))
    parser.add_argument("--horizon", type=int, default=288, help="Forecast horizon in five-minute intervals")
    args = parser.parse_args()

    model, qa = build_model_table(args.input, args.horizon)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.qa_output.parent.mkdir(parents=True, exist_ok=True)
    model.to_csv(args.output, index=False, compression="gzip")
    args.qa_output.write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
