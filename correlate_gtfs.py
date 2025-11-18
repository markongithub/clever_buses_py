import os
import zipfile
import tempfile
import pandas as pd
from datetime import timedelta
import numpy as np
from nearest_stop import StopIndex

GTFS_FILES = [
    "stops.txt",
    "stop_times.txt",
    "trips.txt",
    "routes.txt",
    "calendar.txt",
    "calendar_dates.txt",
]


def extract_gtfs_tables(gtfs_zip_path):
    tmp = tempfile.mkdtemp(prefix="gtfs_")
    with zipfile.ZipFile(gtfs_zip_path) as z:
        for name in GTFS_FILES:
            if name in z.namelist():
                z.extract(name, path=tmp)
    return tmp


def parse_gtfs_time_to_seconds(t):
    # GTFS times can be >24:00:00 (e.g. 25:10:00)
    h, m, s = [int(x) for x in t.split(":")]
    return h * 3600 + m * 60 + s


def build_scheduled_datetimes(stop_times_df, date):
    # date is a pd.Timestamp (local date for schedule)
    secs = stop_times_df["arrival_time"].map(parse_gtfs_time_to_seconds)
    # arrival_seconds may exceed 86400; convert to timedeltas and add to date
    stop_times_df = stop_times_df.copy()
    stop_times_df["arrival_dt"] = pd.to_datetime(date.normalize()) + pd.to_timedelta(
        secs, unit="s"
    )
    return stop_times_df


def correlate(
    buses_parquet, gtfs_zip, output_csv, date="2025-11-16", time_window_minutes=15
):
    # load buses
    buses = pd.read_parquet(buses_parquet)
    print("read input parquet file...")
    if "retrieved_at" not in buses.columns:
        raise RuntimeError("parquet must have 'retrieved_at' timestamp column")
    # ensure datetime64[ns, tz] or naive; normalize to UTC tz-aware for comparisons
    buses["retrieved_at"] = pd.to_datetime(buses["retrieved_at"], utc=True)

    # extract and load GTFS
    gtfs_dir = extract_gtfs_tables(gtfs_zip)
    stops_path = os.path.join(gtfs_dir, "stops.txt")
    stop_times_path = os.path.join(gtfs_dir, "stop_times.txt")
    trips_path = os.path.join(gtfs_dir, "trips.txt")

    stops = pd.read_csv(stops_path, dtype=str)
    stop_times = pd.read_csv(stop_times_path, dtype=str)
    trips = pd.read_csv(trips_path, dtype=str)

    print("Loaded CSV files from GTFS zip...")
    # keep required columns (tolerant to missing optional fields)
    stop_times = stop_times.rename(columns=lambda c: c.strip())
    required_cols = ["trip_id", "arrival_time", "stop_id", "stop_sequence"]
    for c in required_cols:
        if c not in stop_times.columns:
            raise RuntimeError(f"GTFS stop_times.txt missing column {c}")
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    stop_times = stop_times.sort_values(["trip_id", "stop_sequence"])

    # join stop_times -> trips to get route_id / trip_headsign if available
    merged = stop_times.merge(trips, on="trip_id", how="left", suffixes=("", "_trip"))

    # convert GTFS times to datetimes on the target date
    date_ts = pd.Timestamp(date).tz_localize("UTC")
    merged = build_scheduled_datetimes(merged, date_ts)

    # build stop index using workspace class
    stop_index = StopIndex(stops_path)

    rows = []
    window = pd.Timedelta(minutes=time_window_minutes)
    # iterate rows (if very large, sample or optimize later)
    for _, r in buses.iterrows():
        lat = float(r.get("lat", np.nan))
        lon = float(r.get("lon", np.nan))
        if pd.isna(lat) or pd.isna(lon):
            print("No lat/lon, nothing we can do here.")
            continue
        if r.get("rt") != "SY20":
            continue
        nearest = stop_index.find_stop(lat, lon)
        # print(f"Nearest stop: {nearest}")
        # StopIndex.find_stop in workspace returns a stop name / id in other code; try to preserve both cases
        stop_id = None
        # if nearest is a dict-like or string, attempt to get stop_id
        if nearest is None:
            stop_id = None
        elif isinstance(nearest, str):
            # assume nearest is stop_id or stop_name; try to match stops.txt stop_id first
            if nearest in stops["stop_id"].values:
                stop_id = nearest
            else:
                # try match by stop_name
                matches = stops.loc[stops["stop_name"] == nearest, "stop_id"]
                stop_id = matches.iloc[0] if not matches.empty else None
        else:
            # fallback: if the StopIndex returned something else, coerce to str
            try:
                stop_id = str(nearest)
            except Exception:
                stop_id = None

        retrieved_at = pd.to_datetime(r["retrieved_at"], utc=True)
        scheduled_match = None
        if stop_id:
            candidates = merged.loc[merged["stop_id"] == stop_id].copy()
            if not candidates.empty:
                # arrival_dt is tz-aware UTC; compute absolute time diff
                candidates["dt_abs"] = (candidates["arrival_dt"] - retrieved_at).abs()
                within = candidates.loc[candidates["dt_abs"] <= window]
                if not within.empty:
                    best = within.loc[within["dt_abs"].idxmin()]
                    scheduled_match = {
                        "trip_id": best["trip_id"],
                        "route_id": best.get("route_id", ""),
                        "trip_headsign": best.get(
                            "trip_headsign", best.get("trip_headsign_trip", "")
                        ),
                        "scheduled_arrival": best["arrival_dt"],
                        "time_diff_s": int(best["dt_abs"].total_seconds()),
                    }

        new_row = {
            "bus_id": r.get("id", r.get("bid", None)),
            "retrieved_at": retrieved_at,
            "lat": lat,
            "lon": lon,
            "nearest_stop_id": stop_id,
            "nearest_stop_name": nearest,
            "scheduled_trip_id": (
                scheduled_match["trip_id"] if scheduled_match else None
            ),
            "bus_headsign": r["fs"],
            "trip_headsign": (
                scheduled_match["trip_headsign"] if scheduled_match else None
            ),
            "scheduled_route_id": (
                scheduled_match["route_id"] if scheduled_match else None
            ),
            "scheduled_arrival": (
                scheduled_match["scheduled_arrival"] if scheduled_match else None
            ),
            "time_diff_s": scheduled_match["time_diff_s"] if scheduled_match else None,
        }
        if scheduled_match:
            print(f"New row: {new_row}")
        rows.append(new_row)

    out = pd.DataFrame(rows)
    out.to_csv(output_csv, index=False)
    print(f"Wrote {len(out)} correlated rows to {output_csv}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print(
            "usage: python correlate_gtfs.py <buses.parquet> <gtfs_zip> <out.csv> [date YYYY-MM-DD] [window_minutes]"
        )
        sys.exit(1)
    buses_parquet = sys.argv[1]
    gtfs_zip = sys.argv[2]
    out_csv = sys.argv[3]
    date = sys.argv[4] if len(sys.argv) > 4 else "2025-11-16"
    window = int(sys.argv[5]) if len(sys.argv) > 5 else 15
    correlate(buses_parquet, gtfs_zip, out_csv, date=date, time_window_minutes=window)
