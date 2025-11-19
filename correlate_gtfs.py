import os
import zipfile
import tempfile
import pandas as pd
from datetime import timedelta
import numpy as np
from nearest_stop import StopIndex
from zoneinfo import ZoneInfo

GTFS_FILES = [
    "agency.txt",
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


def build_scheduled_datetimes(stop_times_df, date, tzname=None):
    """
    date is a pd.Timestamp (local date for schedule).
    If tzname is provided (e.g. 'America/New_York'), localize schedule datetimes to that
    timezone and convert to UTC (so results are comparable with UTC bus timestamps).
    """
    secs = stop_times_df["arrival_time"].map(parse_gtfs_time_to_seconds)
    stop_times_df = stop_times_df.copy()
    base = pd.to_datetime(date.normalize())
    if tzname:
        # localize to agency local tz then convert to UTC
        local_tz = ZoneInfo(tzname)
        stop_times_df["arrival_dt"] = (
            base.tz_localize(local_tz) + pd.to_timedelta(secs, unit="s")
        ).dt.tz_convert("UTC")
    else:
        # treat date as naive local time and make resulting datetimes timezone-aware UTC
        stop_times_df["arrival_dt"] = (base + pd.to_timedelta(secs, unit="s")).dt.tz_localize("UTC")
    return stop_times_df


def stop_ids_by_headsign(stop_times_df, trips_df, headsign):
    """
    Return a list of stop_ids used by trips whose trip_headsign equals `headsign` exactly.
    Exact match is performed after trimming whitespace. Preserves first-seen order by trip_id and stop_sequence.
    """
    hs = trips_df["trip_headsign"]
    mask = hs == headsign
    if not mask.any():
        return []

    trip_ids = trips_df.loc[mask, "trip_id"].astype(str).unique().tolist()
    if not trip_ids:
        return []

    st = stop_times_df[stop_times_df["trip_id"].isin(trip_ids)]
    if st.empty:
        return []

    return st["stop_id"].unique().tolist()


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

    # try to read agency timezone
    agency_tz = None
    agency_path = os.path.join(gtfs_dir, "agency.txt")
    if os.path.exists(agency_path):
        agency = pd.read_csv(agency_path, dtype=str)
        if "agency_timezone" in agency.columns and not agency["agency_timezone"].dropna().empty:
            agency_tz = agency["agency_timezone"].dropna().iloc[0]
            print(f"Using GTFS agency timezone: {agency_tz}")
        else:
            print("agency.txt found but no agency_timezone column; defaulting to UTC for GTFS times.")
    else:
        print("No agency.txt found in GTFS zip; defaulting to UTC for GTFS times.")

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

    # convert GTFS times to datetimes on the target date (localized to agency timezone then converted to UTC)
    date_ts = pd.Timestamp(date)  # keep as naive local date
    merged = build_scheduled_datetimes(merged, date_ts, tzname=agency_tz)

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
        if r.get("id") != "2477":
            continue
        print(r.to_dict())
        stop_ids_for_headsign = stop_ids_by_headsign(stop_times, trips, r["fs"])
        # print(f"Based on the head sign the stop must be one of {stop_ids_for_headsign}")
        nearest = stop_index.find_stop(lat, lon, frozenset(stop_ids_for_headsign))
        print(f"Nearest stop: {nearest['stop_name']}")
        if nearest is None:
            stop_id = None
        else:
            stop_id = str(nearest["stop_id"])

        retrieved_at = pd.to_datetime(r["retrieved_at"], utc=True)
        scheduled_match = None
        if stop_id:
            candidates = merged.loc[(merged["stop_id"] == stop_id)].copy()
            print(f"Candidates: {candidates}")
            if not candidates.empty:
                # arrival_dt is tz-aware UTC; compute absolute time diff
                candidates["dt_abs"] = (candidates["arrival_dt"] - retrieved_at).abs()
                within = candidates.loc[candidates["dt_abs"] <= window]
                print(f"within: {within}")
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
            "nearest_stop_name": nearest["stop_name"],
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
