# Phase 2 — Leakage-Controlled Data Preparation

## Objective

This phase converts the downloaded SA1 market files into one model-ready table for a 24-hour-ahead, five-minute regional reference price forecast.

Each row is a target dispatch interval. `TARGET_RRP` is the label, and `PREDICTION_CUTOFF_AEST` is exactly 288 five-minute intervals before the target by default.

## Inputs

- SA1 dispatch price
- SA1 dispatch regional summary
- Victoria–South Australia interconnector results
- Optional operational demand actuals
- Optional archived fixed-lead day-ahead weather forecasts

## Leakage controls

- Realised price, demand, generation and interconnector values are shifted by at least the forecast horizon.
- Calendar features are safe because the target timestamp is known in advance.
- Only the archived `previous_day1` weather product is accepted as a direct future feature.
- Weather reanalysis is excluded from the model table.
- Intervention rows are removed before deduplication.
- The target is never copied into an unshifted feature.

## Generated feature groups

- Historical lags at 1 day, 2 days and 8 days relative to the target
- One-day rolling mean and standard deviation
- Seven-day rolling mean
- Time-of-day, day-of-week and month cyclical encodings
- Aggregated day-ahead weather forecast statistics when available

## Run

```bash
python -m pip install -r requirements.txt
python prepare_sa1_model_data.py --input data_sa1
```

The generated CSV and JSON QA report are written under `data_sa1/model/` and are intentionally excluded from Git because they are reproducible outputs.

## Validation

```bash
python -m unittest discover -s tests -v
```

The tests use synthetic five-minute data and verify the 24-hour lag boundary, intervention filtering, timestamp cutoff and weather alignment.

## Next phase

Phase 3 will establish transparent benchmarks before testing more complex models:

1. same-interval previous-day persistence;
2. same-interval previous-week persistence;
3. rolling median benchmark;
4. tree-based baseline with chronological walk-forward validation;
5. MAE, RMSE, spike classification and directional metrics by month and time of day.
