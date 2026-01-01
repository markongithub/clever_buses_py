import html
import os
import zipfile
import tempfile
import pandas as pd
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
OUTPUT_FREQUENCY = 5000
CLEVER_TO_GTFS_SIGN_MISMATCHES = {
    # The headsign in the Clever API is almost always identical to the one in
    # GTFS, but not always.
    "121 James - Sunnycrest Ext": "121 James-Sunnycrest Ext",
    "123 James Street/ To Hub": "123 James Street to Hub",
    # The 220 seems to have "220 James St - Molloy Rd - Airpark" as its Clever
    # headsign often, even when it should be "220 James St - To Hub". Not sure
    # what to do about that yet.
}


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
    # print(f"Calling stop_ids_by_headsign for {headsign}")
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


def fix_headsign_for_gtfs(headsign):
    return CLEVER_TO_GTFS_SIGN_MISMATCHES.get(headsign, headsign)


def best_row_for_observation(merged_df, stop_id, headsign, retrieved_at, window):
    candidates = merged_df.loc[
        (merged_df["stop_id"] == stop_id) & (merged_df["trip_headsign"] == headsign)
    ].copy()
    # print(f"Candidates: {candidates}")
    if candidates.empty:
        print(f"No candidates for {r['fs']} near {stop_id} at {retrieved_at}")
        return None

    # arrival_dt is tz-aware UTC; compute absolute time diff
    candidates["dt_abs"] = (candidates["arrival_dt"] - retrieved_at).abs()
    # TODO: We could make this window flexible if we know a bus is already running very late.
    within = candidates.loc[candidates["dt_abs"] <= window]
    # print(f"within: {within}")
    if within.empty:
        # print("Fucked.")
        return None
    best_index = within["dt_abs"].idxmin()
    return best_index


def build_merged_df(stop_times, stops, routes, trips, date, agency_tz):
    # keep required columns (tolerant to missing optional fields)
    stop_times = stop_times.rename(columns=lambda c: c.strip())
    required_cols = ["trip_id", "arrival_time", "stop_id", "stop_sequence"]
    for c in required_cols:
        if c not in stop_times.columns:
            raise RuntimeError(f"GTFS stop_times.txt missing column {c}")
    stop_times = stop_times[["trip_id", "arrival_time", "stop_id", "stop_sequence"]]
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    stop_times = stop_times.sort_values(["trip_id", "stop_sequence"])

    # join stop_times -> trips to get route_id / trip_headsign if available
    print(f"Service IDs now in trips: {trips['service_id'].unique().tolist()}")
    merged = stop_times.merge(
        trips[["route_id", "service_id", "trip_id", "trip_headsign", "block_id"]],
        on="trip_id",
        how="inner",
        suffixes=("", "_trip"),
    )
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

    return merged


def build_full_schedule(gtfs_dir, date):
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

    calendar_df = pd.read_csv(calendar_path, dtype=str).rename(
        columns=lambda c: c.strip()
    )
    calendar_dates_df = pd.read_csv(calendar_dates_path, dtype=str).rename(
        columns=lambda c: c.strip()
    )
    active_services = service_ids_for_date(calendar_df, calendar_dates_df, target_date)

    print(f"Active services: {active_services}")

    trips_before = len(trips)
    trips = trips[trips["service_id"].astype(str).isin(active_services)].copy()
    print(
        f"Filtered trips by service: {trips_before} -> {len(trips)} active trips on {target_date}"
    )
    debug_service_ids = trips["service_id"].unique().tolist()
    print(f"Service IDs now in trips: {debug_service_ids}")
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

    return build_merged_df(stop_times, stops, routes, trips, date, agency_tz)


def service_ids_for_date(cal, cdates, target_date):
    active_services = set()
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
    return active_services


def correlate(buses_parquet, gtfs_dir, output_csv, date, time_window_minutes=15):
    # load buses
    buses = pd.read_parquet(buses_parquet)
    print("read input parquet file...")
    if "retrieved_at" not in buses.columns:
        raise RuntimeError("parquet must have 'retrieved_at' timestamp column")
    # ensure datetime64[ns, tz] or naive; normalize to UTC tz-aware for comparisons
    buses["retrieved_at"] = pd.to_datetime(buses["retrieved_at"], utc=True)
    buses["fs"] = buses["fs"].apply(html.unescape)

    stops_path = os.path.join(gtfs_dir, "stops.txt")
    stop_times_path = os.path.join(gtfs_dir, "stop_times.txt")
    trips_path = os.path.join(gtfs_dir, "trips.txt")

    stop_times = pd.read_csv(stop_times_path, dtype=str)
    trips = pd.read_csv(trips_path, dtype=str)
    merged = build_full_schedule(gtfs_dir, date)
    # build stop index using workspace class
    stop_index = StopIndex(stops_path)
    window = pd.Timedelta(minutes=time_window_minutes)

    total_bus_rows = len(buses)
    buses_processed = 0
    stop_ids_cache = {}
    for _, r in buses.iterrows():
        buses_processed += 1
        if buses_processed % OUTPUT_FREQUENCY == 0:
            print(f"Processed {buses_processed}/{total_bus_rows}...")
        lat = float(r.get("lat", np.nan))
        lon = float(r.get("lon", np.nan))
        if pd.isna(lat) or pd.isna(lon):
            print("No lat/lon, nothing we can do here.")
            continue
        # if r.get("id") not in ["2481"]:
        #     continue
        if r.get("rt") != CLEVER_ROUTE_ID:
            continue
        # print(r.to_dict())
        fixed_headsign = fix_headsign_for_gtfs(r["fs"])
        stop_ids_from_cache = stop_ids_cache.get(fixed_headsign)
        if stop_ids_from_cache:
            stop_ids_for_headsign = stop_ids_from_cache
        else:
            stop_ids_for_headsign = stop_ids_by_headsign(
                stop_times, trips, fixed_headsign
            )
            stop_ids_cache[fixed_headsign] = stop_ids_for_headsign
        # print(f"Based on the head sign the stop must be one of {stop_ids_for_headsign}")
        nearest = stop_index.find_stop(lat, lon, frozenset(stop_ids_for_headsign))
        if nearest is None:
            # print(
            #    f"{r['retrieved_at']} bus {r['id']} with head sign {r['fs']} was at ({lat},{lon}) but no scheduled stop is near there."
            # )
            continue
        else:
            # print(f"Nearest stop: {nearest['stop_name']}")
            stop_id = str(nearest["stop_id"])

        retrieved_at = pd.to_datetime(r["retrieved_at"], utc=True)
        # print(
        #    f"Considering bus {r['id']} at {nearest['stop_name']} at {retrieved_at}..."
        # )
        if not stop_id:
            continue
        best_index = best_row_for_observation(
            merged, stop_id, fixed_headsign, retrieved_at, window
        )
        if best_index is None:
            # print("We didn't get a best row. Fucked.")
            continue
        # print(f"best_index: {best_index}")
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
                (retrieved_at - merged.at[best_index, "arrival_dt"]).total_seconds()
            )
        else:
            recorded_bus = merged.at[best_index, "bus_id"]
            if recorded_bus == r["id"]:
                # print(
                #    f"Bus {r['id']} with head sign {r['fs']} was already at {nearest['stop_name']} so we won't edit the arrival data."
                # )
                pass
            else:
                print(
                    f"Uh oh. We saw bus {recorded_bus} at {nearest['stop_name']} at {merged.at[best_index, "observed_at"]} but at {retrieved_at} we have {r["id"]}"
                )
    summarize_findings(merged)
    merged.to_csv(output_csv, index=False)


def summarize_findings(stop_times_merged_df):
    """
    Summarize correlation findings by counting trips with and without observed_at data.
    """
    # Group by trip_id to analyze at the trip level
    trip_groups = stop_times_merged_df.groupby("trip_id")

    # Identify trips with and without observations
    trips_with_obs_mask = trip_groups["observed_at"].apply(lambda x: x.notna().any())
    trips_with_observations = trips_with_obs_mask.sum()

    # Total unique trips
    total_trips = len(trip_groups)

    # Trips without any observations
    trips_without_observations = total_trips - trips_with_observations

    # Stop-level statistics
    total_stops = len(stop_times_merged_df)
    observed_stops = stop_times_merged_df["observed_at"].notna().sum()
    unobserved_stops = total_stops - observed_stops

    print("\n" + "=" * 60)
    print("CORRELATION SUMMARY")
    print("=" * 60)
    print(f"\nTrip-level statistics:")
    print(f"  Total trips: {total_trips}")
    print(
        f"  Trips with observations: {trips_with_observations} ({trips_with_observations/total_trips*100:.1f}%)"
    )
    print(
        f"  Trips without observations: {trips_without_observations} ({trips_without_observations/total_trips*100:.1f}%)"
    )
    # List trips without observations
    if trips_without_observations > 0:
        print(f"\nTrips without observations ({trips_without_observations} total):")
        print("-" * 60)

        # Get trip_ids without observations
        trips_without_obs_ids = trips_with_obs_mask[~trips_with_obs_mask].index.tolist()

        # Get details for each trip without observations
        unobserved_trips = stop_times_merged_df[
            stop_times_merged_df["trip_id"].isin(trips_without_obs_ids)
        ].copy()

        # Get first stop for each trip (sorted by stop_sequence)
        first_stops = (
            unobserved_trips.sort_values("stop_sequence")
            .groupby("trip_id")
            .first()
            .reset_index()
        )

        # Sort by departure time
        first_stops = first_stops.sort_values("arrival_dt")

        for _, trip in first_stops.iterrows():
            trip_id = trip["trip_id"]
            headsign = trip.get("trip_headsign", "Unknown")
            departure = trip["arrival_dt"]
            block = trip["block_id"]
            print(f"  {trip_id} from block {block}: {headsign} @ {departure}")

    print("=" * 60 + "\n")
    print(f"Stop-level statistics:")
    print(f"  Total scheduled stops: {total_stops}")
    print(
        f"  Stops with observations: {observed_stops} ({observed_stops/total_stops*100:.1f}%)"
    )
    print(
        f"  Stops without observations: {unobserved_stops} ({unobserved_stops/total_stops*100:.1f}%)"
    )


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
        default=20,
        help="Time window in minutes for matching (default: 20)",
    )

    args = parser.parse_args()

    correlate(
        args.buses,
        args.gtfs_dir,
        args.output,
        date=args.date,
        time_window_minutes=args.window,
    )
