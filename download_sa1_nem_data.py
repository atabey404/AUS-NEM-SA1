#!/usr/bin/env python3
"""Download and filter AEMO NEM data for SA1.

Default archive window is the latest 36 complete MMSDM months available when
this starter pack was produced: 2023-07 through 2026-06.

The script uses only the Python standard library. It downloads one ZIP at a
time, filters its CSV payload while streaming, appends to gzip-compressed CSV,
and removes the ZIP unless --keep-zips is supplied.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path


BASE = "https://nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM"
REGION = "SA1"
SA_INTERCONNECTORS = {"V-SA", "V-S-MNSP1"}

WEATHER_POINTS = [
    ("Adelaide", -34.9285, 138.6007, "demand/metro proxy"),
    ("Port_Augusta", -32.4952, 137.7894, "north/solar proxy"),
    ("Whyalla", -33.0250, 137.5614, "upper Spencer Gulf proxy"),
    ("Ceduna", -32.1260, 133.6763, "far-west wind/solar proxy"),
    ("Mount_Gambier", -37.8284, 140.7804, "south-east wind/demand proxy"),
]


@dataclass(frozen=True)
class TableSpec:
    table: str
    subdir: str
    filter_field: str
    allowed: frozenset[str] | None
    output_name: str
    profile: str
    add_fuel: bool = False


TABLES = [
    TableSpec("DISPATCHPRICE", "DATA", "REGIONID", frozenset({REGION}), "dispatch_price", "core"),
    TableSpec("DISPATCHREGIONSUM", "DATA", "REGIONID", frozenset({REGION}), "dispatch_region_summary", "core"),
    TableSpec("DEMANDOPERATIONALACTUAL", "DATA", "REGIONID", frozenset({REGION}), "operational_demand_actual", "core"),
    TableSpec("DISPATCHINTERCONNECTORRES", "DATA", "INTERCONNECTORID", frozenset(SA_INTERCONNECTORS), "dispatch_interconnector", "core"),
    TableSpec("DISPATCH_UNIT_SCADA", "DATA", "DUID", None, "dispatch_unit_scada", "full", True),
    TableSpec("PREDISPATCHPRICE", "PREDISP_ALL_DATA", "REGIONID", frozenset({REGION}), "predispatch_price", "full"),
    TableSpec("PREDISPATCHREGIONSUM", "PREDISP_ALL_DATA", "REGIONID", frozenset({REGION}), "predispatch_region_summary", "full"),
    TableSpec("PREDISPATCHINTERCONNECTORRES", "PREDISP_ALL_DATA", "INTERCONNECTORID", frozenset(SA_INTERCONNECTORS), "predispatch_interconnector", "full"),
    TableSpec("P5MIN_REGIONSOLUTION", "P5MIN_ALL_DATA", "REGIONID", frozenset({REGION}), "p5min_region_solution", "full"),
    TableSpec("P5MIN_INTERCONNECTORSOLN", "P5MIN_ALL_DATA", "INTERCONNECTORID", frozenset(SA_INTERCONNECTORS), "p5min_interconnector_solution", "full"),
]


def month_iter(start: str, end: str):
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    if (sy, sm) > (ey, em):
        raise ValueError("--start must not be after --end")
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def candidate_urls(year: int, month: int, spec: TableSpec):
    ym = f"{year:04d}_{month:02d}"
    stamp = f"{year:04d}{month:02d}010000"
    root = f"{BASE}/{year:04d}/MMSDM_{ym}/MMSDM_Historical_Data_SQLLoader/{spec.subdir}"
    if spec.subdir == "DATA":
        new_name = f"PUBLIC_ARCHIVE#{spec.table}#FILE01#{stamp}.zip"
    else:
        new_name = f"PUBLIC_ARCHIVE#{spec.table}#ALL#FILE01#{stamp}.zip"
    old_name = f"PUBLIC_DVD_{spec.table}_{stamp}.zip"
    for name in (new_name, old_name):
        yield f"{root}/{urllib.parse.quote(name, safe='')}"


def download_first(urls, destination: Path, retries: int = 3) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in urls:
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SA1-NEM-research/1.0"})
                with urllib.request.urlopen(req, timeout=180) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                return url
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    errors.append(f"404 {url}")
                    break
                errors.append(f"HTTP {exc.code} {url} attempt {attempt}")
            except Exception as exc:  # network/timeout
                errors.append(f"{type(exc).__name__}: {exc} ({url}, attempt {attempt})")
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError("No archive candidate succeeded:\n" + "\n".join(errors[-8:]))


def load_duid_map(path: Path) -> dict[str, str]:
    mapping = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            duid = (row.get("DUID") or "").strip()
            if duid:
                mapping[duid] = (row.get("FUEL_CLASS") or "Other").strip()
    if not mapping:
        raise RuntimeError(f"No DUIDs found in {path}")
    return mapping


def process_mms_zip(zip_path: Path, output_path: Path, spec: TableSpec, duid_map: dict[str, str]) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    append = output_path.exists() and output_path.stat().st_size > 0
    rows_written = 0
    allowed = frozenset(duid_map) if spec.add_fuel else (spec.allowed or frozenset())
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
        if not names:
            raise RuntimeError(f"No CSV payload in {zip_path}")
        with zf.open(names[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="") as text:
            reader = csv.reader(text)
            header = None
            header_index = None
            mode = "at" if append else "wt"
            with gzip.open(output_path, mode, encoding="utf-8", newline="") as out:
                writer = csv.writer(out)
                for row in reader:
                    if not row:
                        continue
                    if row[0] == "I":
                        header = row[4:]
                        if spec.filter_field not in header:
                            raise RuntimeError(f"{spec.filter_field} missing from {spec.table} header")
                        header_index = {name: i for i, name in enumerate(header)}
                        if not append:
                            writer.writerow(header + (["FUEL_CLASS"] if spec.add_fuel else []))
                        continue
                    if row[0] != "D" or header is None or header_index is None:
                        continue
                    data = row[4:]
                    key = data[header_index[spec.filter_field]].strip()
                    if key not in allowed:
                        continue
                    if spec.add_fuel:
                        data = data + [duid_map.get(key, "Other")]
                    writer.writerow(data)
                    rows_written += 1
    return rows_written


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SA1-NEM-research/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def write_weather(output: Path, start_date: str, end_date: str, kind: str):
    output.parent.mkdir(parents=True, exist_ok=True)
    if kind == "actual_proxy":
        endpoint = "https://archive-api.open-meteo.com/v1/archive"
        variables = ["temperature_2m", "cloud_cover", "shortwave_radiation", "wind_speed_100m"]
        filename = "weather_reanalysis_proxy_hourly.csv.gz"
    elif kind == "day_ahead":
        endpoint = "https://previous-runs-api.open-meteo.com/v1/forecast"
        variables = [
            "temperature_2m_previous_day1",
            "cloud_cover_previous_day1",
            "shortwave_radiation_previous_day1",
            "wind_speed_100m_previous_day1",
        ]
        filename = "weather_day_ahead_previous_run_hourly.csv.gz"
        if start_date < "2024-01-01":
            start_date = "2024-01-01"
    else:
        raise ValueError(kind)

    target = output / filename
    with gzip.open(target, "wt", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["POINT_ID", "LATITUDE", "LONGITUDE", "POINT_ROLE", "TIME_AEST", *variables])
        for point_id, lat, lon, role in WEATHER_POINTS:
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": ",".join(variables),
                "timezone": "Australia/Brisbane",
                "wind_speed_unit": "ms",
            }
            payload = fetch_json(endpoint + "?" + urllib.parse.urlencode(params))
            times = payload["hourly"]["time"]
            arrays = [payload["hourly"].get(v, [None] * len(times)) for v in variables]
            for i, t in enumerate(times):
                writer.writerow([point_id, lat, lon, role, t, *[a[i] for a in arrays]])
    print(f"weather: wrote {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-07", help="First archive month YYYY-MM")
    parser.add_argument("--end", default="2026-06", help="Last archive month YYYY-MM")
    parser.add_argument("--profile", choices=["core", "full"], default="core")
    parser.add_argument("--weather", choices=["none", "actual", "day-ahead", "both"], default="none")
    parser.add_argument("--output", type=Path, default=Path("data_sa1"))
    parser.add_argument("--duid-map", type=Path, default=Path(__file__).with_name("sa1_duid_fuel_map.csv"))
    parser.add_argument("--keep-zips", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Stop if any table-month is unavailable")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "_cache"
    duid_map = load_duid_map(args.duid_map)
    selected = [t for t in TABLES if t.profile == "core" or args.profile == "full"]
    manifest_path = args.output / "download_log.csv"
    new_log = not manifest_path.exists()
    with manifest_path.open("a", encoding="utf-8", newline="") as log_file:
        log = csv.writer(log_file)
        if new_log:
            log.writerow(["MONTH", "TABLE", "STATUS", "ROWS", "SOURCE_URL", "MESSAGE"])
        for y, m in month_iter(args.start, args.end):
            ym = f"{y:04d}-{m:02d}"
            for spec in selected:
                zip_path = cache / f"{spec.table}_{y:04d}{m:02d}.zip"
                try:
                    source_url = download_first(candidate_urls(y, m, spec), zip_path)
                    rows = process_mms_zip(zip_path, args.output / f"{spec.output_name}.csv.gz", spec, duid_map)
                    log.writerow([ym, spec.table, "OK", rows, source_url, ""])
                    log_file.flush()
                    print(f"{ym} {spec.table}: {rows:,} rows")
                except Exception as exc:
                    log.writerow([ym, spec.table, "SKIPPED", 0, "", str(exc).replace("\n", " | ")])
                    log_file.flush()
                    print(f"WARNING {ym} {spec.table}: {exc}", file=sys.stderr)
                    if args.strict:
                        raise
                finally:
                    if zip_path.exists() and not args.keep_zips:
                        zip_path.unlink()

    start_date = args.start + "-01"
    ey, em = map(int, args.end.split("-"))
    if em == 12:
        next_month = date(ey + 1, 1, 1)
    else:
        next_month = date(ey, em + 1, 1)
    end_date = date.fromordinal(next_month.toordinal() - 1).isoformat()
    if args.weather in ("actual", "both"):
        write_weather(args.output, start_date, end_date, "actual_proxy")
    if args.weather in ("day-ahead", "both"):
        write_weather(args.output, start_date, end_date, "day_ahead")

    print(f"Done. Output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
