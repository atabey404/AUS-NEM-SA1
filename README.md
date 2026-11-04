# AUS-NEM-SA1

An English-language starter project for five-minute data, market concepts, leakage controls, and price forecasting in the South Australian `SA1` region of the Australian National Electricity Market.

## Project scope

- Region: `SA1`
- Primary time grain: five minutes
- Initial complete archive window: 2023-07 to 2026-06
- Core data: regional spot price, regional dispatch summary, operational demand, and interconnectors
- Extended data: DUID-level SCADA, 30-minute pre-dispatch, five-minute P5MIN, and weather
- Core rule: every feature must satisfy `available_time <= prediction_cutoff`

## Repository contents

| File | Purpose |
| --- | --- |
| `download_sa1_nem_data.py` | Downloads and filters AEMO NEMWeb data by month |
| `sa1_duid_fuel_map.csv` | Maps SA1 DUIDs to fuel and technology classes |
| `AEMO_SA1_Data_Dictionary.xlsx` | Defines fields, units, sources, publication times, forecast availability, and leakage risk |
| `NEM_Market_Overview.docx` | English overview of the NEM and the SA1 modelling boundary |
| `SA1_core_2023-07_2026-06_QA.csv` | Quality checks for the three-year core dataset |
| `SA1_weather_QA.csv` | Quality checks for the weather datasets |

## Quick start

Download the core profile:

```bash
python download_sa1_nem_data.py \
  --start 2023-07 \
  --end 2026-06 \
  --profile core \
  --output data_sa1
```

Download the full profile and both weather products:

```bash
python download_sa1_nem_data.py \
  --start 2023-07 \
  --end 2026-06 \
  --profile full \
  --weather both \
  --output data_sa1
```

The script uses only the Python standard library. The `full` profile is large, so process it incrementally by month.

## Data and leakage controls

1. The NEM has used five-minute settlement since 1 October 2021. This project retains a five-minute fact layer.
2. Future realised RRP, actual demand, actual SCADA, and actual interconnector flow are labels or post-event validation data, not forecast features.
3. Pre-dispatch data must retain both the target interval and forecast vintage. Select only runs published at or before the prediction cutoff.
4. Weather reanalysis is for exploration or retrospective validation only. Day-ahead models should use archived fixed-lead forecasts.
5. Validation uses rolling chronological splits, never random shuffling.

## Data-file policy

This repository does not host the complete three-year market and weather datasets. They are large, change over time, and can be reproduced from AEMO and the weather provider with the included script. The repository keeps code, mappings, QA results, documentation, and subsequent modelling outputs.

## Official sources

- [AEMO NEM Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem)
- [NEMWeb](https://visualisations.aemo.com.au/aemo/nemweb/)
- [Operational Demand Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/operational-demand-data)
- [Pre-dispatch](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/pre-dispatch)

## Update policy

Future data processing, feature engineering, models, validation results, and documentation will be committed to this repository. Secrets, local absolute paths, temporary files, and complete raw datasets will not be uploaded.
