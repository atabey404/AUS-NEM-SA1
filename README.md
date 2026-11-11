# AUS-NEM-SA1

An English-language research project for five-minute data preparation, leakage control and day-ahead price forecasting in the South Australian `SA1` region of the Australian National Electricity Market.

## Project status

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Market concepts, sources, downloader, data dictionary and source QA | Complete |
| 2 | Leakage-controlled model-table preparation | Complete |
| 3 | Transparent benchmarks and chronological validation | Pipeline complete; full-data run pending |
| 4 | Model improvement, diagnostics and operational forecast workflow | Next after baseline results |

## Modelling objective

- Region: `SA1`
- Target: five-minute regional reference price (`RRP`)
- Forecast horizon: 24 hours, or 288 five-minute intervals
- Initial archive window: 2023-07 to 2026-06
- Core rule: every feature must satisfy `available_time <= prediction_cutoff`
- Validation rule: chronological walk-forward evaluation only; never random shuffling

## Repository contents

| File | Purpose |
| --- | --- |
| `download_sa1_nem_data.py` | Downloads and filters AEMO NEMWeb data by month |
| `prepare_sa1_model_data.py` | Builds a leakage-controlled day-ahead modelling table |
| `evaluate_sa1_baselines.py` | Runs monthly walk-forward benchmark evaluation |
| `requirements.txt` | Python dependencies for data preparation and modelling |
| `tests/test_prepare_sa1_model_data.py` | Synthetic tests for lag boundaries, intervention filtering and weather alignment |
| `tests/test_evaluate_sa1_baselines.py` | Synthetic tests for chronological folds and benchmark availability |
| `PHASE_2_DATA_PREPARATION.md` | Phase 2 design, assumptions, controls and validation notes |
| `PHASE_3_BASELINES.md` | Phase 3 benchmark definitions, metrics and acceptance rules |
| `sa1_duid_fuel_map.csv` | Maps SA1 DUIDs to fuel and technology classes |
| `AEMO_SA1_Data_Dictionary.xlsx` | Defines fields, units, sources, publication times and leakage risk |
| `NEM_Market_Overview.docx` | Overview of the NEM and the SA1 modelling boundary |
| `SA1_core_2023-07_2026-06_QA.csv` | Quality checks for the three-year core dataset |
| `SA1_weather_QA.csv` | Quality checks for the weather datasets |

## Quick start

Install the data-preparation dependencies:

```bash
python -m pip install -r requirements.txt
```

Download the core market profile:

```bash
python download_sa1_nem_data.py \
  --start 2023-07 \
  --end 2026-06 \
  --profile core \
  --output data_sa1
```

Download the full profile and the archived weather products:

```bash
python download_sa1_nem_data.py \
  --start 2023-07 \
  --end 2026-06 \
  --profile full \
  --weather both \
  --output data_sa1
```

Build the 24-hour-ahead model table:

```bash
python prepare_sa1_model_data.py --input data_sa1
```

Run the monthly walk-forward baselines:

```bash
python evaluate_sa1_baselines.py \
  --input data_sa1/model/sa1_day_ahead_features.csv.gz \
  --output-dir data_sa1/evaluation
```

Run the validation tests:

```bash
python -m unittest discover -s tests -v
```

The generated model table and its JSON QA report are written under `data_sa1/model/`. Generated datasets are deliberately excluded from Git because they can be reproduced from the source archives.

## Phase 3 benchmark boundary

The evaluation pipeline compares previous-day persistence, previous-week persistence, a seven-day rolling median and a robust tree baseline. Test periods are complete calendar months, and every training row is strictly earlier than its test month. Results include MAE, RMSE, median absolute error, bias, direction accuracy and price-spike metrics.

## Phase 2 feature boundary

Each row in the generated table represents one future five-minute interval:

- `TARGET_TIME_AEST` identifies the interval being forecast.
- `PREDICTION_CUTOFF_AEST` is 24 hours before that target by default.
- `TARGET_RRP` is the realised label and is never used as an unshifted feature.
- Realised market features use lags of at least 288 intervals.
- Calendar variables are known in advance.
- Archived fixed-lead `previous_day1` weather forecasts may be joined to their target times.
- Weather reanalysis and future realised market values are excluded from forecast features.

## Data and leakage controls

1. The NEM has used five-minute settlement since 1 October 2021, so this project retains a five-minute fact layer.
2. Future realised RRP, actual demand, SCADA and interconnector flow are labels or retrospective validation data, not contemporaneous forecast features.
3. Intervention rows are removed before timestamp deduplication.
4. Pre-dispatch data must retain both target interval and forecast vintage. A run is eligible only when it was published at or before the prediction cutoff.
5. Weather reanalysis is for exploration or retrospective validation only. Day-ahead models use archived fixed-lead forecasts.
6. Operational demand actuals are optional and are always shifted behind the forecast cutoff.

## Data-file policy

This repository does not host the complete three-year market and weather datasets. They are large, change over time and can be reproduced from AEMO and the weather provider with the included scripts. The repository keeps code, mappings, QA results, documentation and modelling outputs that are small enough to review.

## Official sources

- [AEMO NEM Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem)
- [AEMO MMS Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data)
- [AEMO Dispatch Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/dispatch)
- [AEMO Pre-dispatch Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/pre-dispatch)
- [AEMO Operational Demand Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/operational-demand-data)
- [NEMWeb](https://visualisations.aemo.com.au/aemo/nemweb/)

## Update policy

Future data processing, feature engineering, models, validation results and documentation will be committed to this repository in English. Secrets, local absolute paths, temporary files and complete raw datasets will not be uploaded.
