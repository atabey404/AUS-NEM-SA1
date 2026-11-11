# Phase 3 — Baselines and Walk-Forward Validation

## Objective

This phase establishes transparent performance floors before any complex SA1 price model is accepted.

## Forecasts compared

1. **Previous day:** the RRP from the same five-minute interval one day earlier.
2. **Previous week:** the RRP from the same five-minute interval seven days earlier.
3. **Rolling median:** the median RRP from the seven days ending at the prediction cutoff.
4. **Tree baseline:** a histogram gradient boosting regressor using only leakage-controlled Phase 2 features.

The tree baseline uses absolute-error loss to reduce sensitivity to rare extreme prices. It is a benchmark, not yet the final operational model.

## Validation design

- Test windows are whole calendar months.
- Each model is trained only on rows strictly earlier than the test month.
- The default training window is the latest 365 days, capped at 120,000 rows.
- The first 90 days are reserved as minimum training history.
- No random train/test split is used.
- Each fold writes its training and test boundaries and a chronology check to JSON.

## Metrics

- MAE
- RMSE
- Median absolute error
- Mean bias
- Direction accuracy relative to the previous-day price
- Price-spike precision, recall and F1 using an absolute RRP threshold of AUD 300/MWh by default

## Run

```bash
python prepare_sa1_model_data.py --input data_sa1
python evaluate_sa1_baselines.py \
  --input data_sa1/model/sa1_day_ahead_features.csv.gz \
  --output-dir data_sa1/evaluation
```

Outputs:

- `sa1_baseline_metrics.csv`
- `sa1_baseline_predictions.csv.gz`
- `sa1_baseline_run.json`

These reproducible generated outputs remain outside Git by default. Small reviewed result summaries may be committed after a full-data run.

## Acceptance rule for the next model

A more complex model should not replace the baseline unless it:

1. improves overall MAE and median absolute error;
2. remains stable across monthly folds;
3. does not materially worsen mean bias;
4. improves either direction accuracy or spike F1 without using future information;
5. can reproduce the same result from a saved configuration.

## Current limitation

The repository intentionally excludes the complete raw dataset. The pipeline and chronology tests are complete, but final numerical performance must be produced in an environment containing the downloaded `data_sa1` directory.
