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
GTFS_ROUTE_ID = "Sy 20"
CLEVER_ROUTE_ID = "SY20"


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
        stop_times_df["arrival_dt"] = (
            base + pd.to_timedelta(secs, unit="s")
        ).dt.tz_localize("UTC")
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


def correlate(buses_parquet, gtfs_dir, output_csv, date, time_window_minutes=15):
    # load buses
    buses = pd.read_parquet(buses_parquet)
    print("read input parquet file...")
    if "retrieved_at" not in buses.columns:
        raise RuntimeError("parquet must have 'retrieved_at' timestamp column")
    # ensure datetime64[ns, tz] or naive; normalize to UTC tz-aware for comparisons
    buses["retrieved_at"] = pd.to_datetime(buses["retrieved_at"], utc=True)

    stops_path = os.path.join(gtfs_dir, "stops.txt")
    stop_times_path = os.path.join(gtfs_dir, "stop_times.txt")
    trips_path = os.path.join(gtfs_dir, "trips.txt")
    routes_path = os.path.join(gtfs_dir, "routes.txt")

    stops = pd.read_csv(stops_path, dtype=str)
    stop_times = pd.read_csv(stop_times_path, dtype=str)
    trips = pd.read_csv(trips_path, dtype=str)
    routes = pd.read_csv(routes_path, dtype=str)

    # --- START: filter trips by active service_id using calendar / calendar_dates ---
    target_date = pd.to_datetime(date).date()

    calendar_path = os.path.join(gtfs_dir, "calendar.txt")
    calendar_dates_path = os.path.join(gtfs_dir, "calendar_dates.txt")

    calendar_found = False
    calendar_dates_found = False
    active_services = set()

    if os.path.exists(calendar_path):
        calendar_found = True
        cal = pd.read_csv(calendar_path, dtype=str).rename(columns=lambda c: c.strip())
        if {"service_id", "start_date", "end_date"}.issubset(cal.columns):
            cal["start_date"] = pd.to_datetime(
                cal["start_date"], format="%Y%m%d", errors="coerce"
            ).dt.date
            cal["end_date"] = pd.to_datetime(
                cal["end_date"], format="%Y%m%d", errors="coerce"
            ).dt.date
            weekday_cols = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            weekday_col = weekday_cols[target_date.weekday()]
            if weekday_col in cal.columns:
                mask = (
                    cal["start_date"].notna()
                    & cal["end_date"].notna()
                    & (cal["start_date"] <= target_date)
                    & (cal["end_date"] >= target_date)
                    & (cal[weekday_col].astype(str).str.strip() == "1")
                )
                active_services.update(cal.loc[mask, "service_id"].astype(str).tolist())
        else:
            print("calendar.txt present but missing required columns; ignoring.")
    if os.path.exists(calendar_dates_path):
        calendar_dates_found = True
        cdates = pd.read_csv(calendar_dates_path, dtype=str).rename(
            columns=lambda c: c.strip()
        )
        if {"service_id", "date", "exception_type"}.issubset(cdates.columns):
            cdates["date_parsed"] = pd.to_datetime(
                cdates["date"], format="%Y%m%d", errors="coerce"
            ).dt.date
            adds = (
                cdates.loc[
                    (cdates["date_parsed"] == target_date)
                    & (cdates["exception_type"].astype(str).str.strip() == "1"),
                    "service_id",
                ]
                .astype(str)
                .tolist()
            )
            removes = (
                cdates.loc[
                    (cdates["date_parsed"] == target_date)
                    & (cdates["exception_type"].astype(str).str.strip() == "2"),
                    "service_id",
                ]
                .astype(str)
                .tolist()
            )
            active_services.update(adds)
            active_services.difference_update(removes)
        else:
            print("calendar_dates.txt present but missing required columns; ignoring.")

    if calendar_found or calendar_dates_found:
        print(f"Active services: {active_services}")
        if "service_id" in trips.columns:
            trips_before = len(trips)
            trips = trips[trips["service_id"].astype(str).isin(active_services)].copy()
            print(
                f"Filtered trips by service: {trips_before} -> {len(trips)} active trips on {target_date}"
            )
            debug_service_ids = trips["service_id"].unique().tolist()
            print(f"Service IDs now in trips: {debug_service_ids}")
        else:
            print(
                "Calendar files found but trips.txt has no service_id; skipping service filtering."
            )
    else:
        print("No calendar/calendar_dates found; not filtering trips by service date.")
    # --- END: calendar filtering ---

    # try to read agency timezone
    agency_tz = None
    agency_path = os.path.join(gtfs_dir, "agency.txt")
    if os.path.exists(agency_path):
        agency = pd.read_csv(agency_path, dtype=str)
        if (
            "agency_timezone" in agency.columns
            and not agency["agency_timezone"].dropna().empty
        ):
            agency_tz = agency["agency_timezone"].dropna().iloc[0]
            print(f"Using GTFS agency timezone: {agency_tz}")
        else:
            print(
                "agency.txt found but no agency_timezone column; defaulting to UTC for GTFS times."
            )
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
    print(f"Service IDs now in trips: {trips['service_id'].unique().tolist()}")
    merged = stop_times.merge(trips, on="trip_id", how="inner", suffixes=("", "_trip"))
    # This is just for debugging, remove it later
    merged = merged.merge(
        stops[["stop_id", "stop_name"]],
        on="stop_id",
        how="inner",
    )
    merged = merged.merge(
        routes[["route_id", "route_short_name"]],
        on="route_id",
        how="inner",
    )
    # merged = merged.loc[merged["block_id"] == "268630"]
    merged = merged.loc[merged["route_short_name"] == GTFS_ROUTE_ID]
    print(f"Service IDs now in merged: {merged['service_id'].unique().tolist()}")

    # convert GTFS times to datetimes on the target date (localized to agency timezone then converted to UTC)
    date_ts = pd.Timestamp(date)  # keep as naive local date
    merged = build_scheduled_datetimes(merged, date_ts, tzname=agency_tz)

    # add placeholder columns for observed data; they'll be populated later
    merged["observed_at"] = pd.Series(dtype="datetime64[ns, UTC]")
    merged["bus_id"] = None
    merged["lat"] = np.nan
    merged["lon"] = np.nan
    merged["late"] = None

    # build stop index using workspace class
    stop_index = StopIndex(stops_path)
    rows = []
    window = pd.Timedelta(minutes=time_window_minutes)
    # This sucks. It only works on one day at a time and would completely fail if a trip crossed midnight local time.
    print(f"Service IDs now in trips: {debug_service_ids}")
    for _, r in buses.iterrows():
        lat = float(r.get("lat", np.nan))
        lon = float(r.get("lon", np.nan))
        if pd.isna(lat) or pd.isna(lon):
            print("No lat/lon, nothing we can do here.")
            continue
        if r.get("id") not in ["2481"]:
            continue
        # if r.get("rt") != CLEVER_ROUTE_ID:
        #     continue
        # print(r.to_dict())
        stop_ids_for_headsign = stop_ids_by_headsign(stop_times, trips, r["fs"])
        # print(f"Based on the head sign the stop must be one of {stop_ids_for_headsign}")
        nearest = stop_index.find_stop(lat, lon, frozenset(stop_ids_for_headsign))
        if nearest is None:
            print(
                f"{r['retrieved_at']} bus {r['id']} with head sign {r['fs']} was at ({lat},{lon}) but no scheduled stop is near there."
            )
            continue
        else:
            # print(f"Nearest stop: {nearest['stop_name']}")
            stop_id = str(nearest["stop_id"])

        retrieved_at = pd.to_datetime(r["retrieved_at"], utc=True)
        # print(f"Considering bus {r['id']} at {nearest['stop_name']} at {retrieved_at}...")
        if stop_id:
            candidates = merged.loc[
                (merged["stop_id"] == stop_id) & (merged["trip_headsign"] == r["fs"])
            ].copy()
            # print(f"Candidates: {candidates}")
            if not candidates.empty:
                # arrival_dt is tz-aware UTC; compute absolute time diff
                # TODO: stop using absolute value. Make early negative and late positive. Or the other way around.
                candidates["dt_abs"] = (candidates["arrival_dt"] - retrieved_at).abs()
                within = candidates.loc[candidates["dt_abs"] <= window]
                # print(f"within: {within}")
                if not within.empty:
                    best_index = within["dt_abs"].idxmin()
                    best = within.loc[best_index]
                    # Only populate if we haven't already observed this scheduled stop
                    if (
                        pd.isna(merged.at[best_index, "observed_at"])
                        or merged.at[best_index, "stop_sequence"] == 1
                    ):
                        merged.at[best_index, "observed_at"] = retrieved_at
                        merged.at[best_index, "bus_id"] = r["id"]
                        merged.at[best_index, "lat"] = lat
                        merged.at[best_index, "lon"] = lon
                        merged.at[best_index, "late"] = int(
                            (retrieved_at - best["arrival_dt"]).total_seconds()
                        )
                    else:
                        recorded_bus = merged.at[best_index, "bus_id"]
                        if recorded_bus == r["id"]:
                            print(
                                f"Bus {r['id']} with head sign {r['fs']} was already at {nearest['stop_name']} so we won't edit the arrival data."
                            )
                        else:
                            print(
                                f"Uh oh. We saw bus {recorded_bus} at {nearest['stop_name']} at {merged.at[best_index, "observed_at"]} but at {retrieved_at} we have {r["id"]}"
                            )

    merged.to_csv(output_csv, index=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Correlate bus location data with GTFS scheduled stops"
    )
    parser.add_argument(
        "--buses",
        required=True,
        help="Path to the buses parquet file",
    )
    parser.add_argument(
        "--gtfs-dir",
        required=True,
        help="Path to the GTFS directory containing extracted GTFS files",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the output CSV file",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=15,
        help="Time window in minutes for matching (default: 15)",
    )

    args = parser.parse_args()

    correlate(
        args.buses,
        args.gtfs_dir,
        args.output,
        date=args.date,
        time_window_minutes=args.window,
    )
