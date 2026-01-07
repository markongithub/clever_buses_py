import os
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo

GTFS_ROUTE_ID = "Sy 20"


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


def build_merged_df(stop_times_orig, stops, routes, trips, date, agency_tz):
    # keep required columns (tolerant to missing optional fields)
    stop_times = stop_times_orig.copy().rename(columns=lambda c: c.strip())
    required_cols = ["trip_id", "arrival_time", "stop_id", "stop_sequence"]
    for c in required_cols:
        if c not in stop_times.columns:
            raise RuntimeError(f"GTFS stop_times.txt missing column {c}")
    stop_times = stop_times[
        ["trip_id", "arrival_time", "stop_id", "stop_sequence", "shape_dist_traveled"]
    ]
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
    merged["estimated_at"] = pd.Series(dtype="datetime64[ns, UTC]")
    merged["bus_id"] = None
    merged["lat"] = np.nan
    merged["lon"] = np.nan
    merged["late"] = None
    merged["gtfs_date"] = date

    return merged


def build_full_schedule(gtfs_dir, dates):
    stops_path = os.path.join(gtfs_dir, "stops.txt")
    stop_times_path = os.path.join(gtfs_dir, "stop_times.txt")
    trips_path = os.path.join(gtfs_dir, "trips.txt")
    routes_path = os.path.join(gtfs_dir, "routes.txt")

    stops = pd.read_csv(stops_path, dtype=str)
    stop_times = pd.read_csv(stop_times_path, dtype=str)
    trips_immutable = pd.read_csv(trips_path, dtype=str)
    routes = pd.read_csv(routes_path, dtype=str)

    calendar_path = os.path.join(gtfs_dir, "calendar.txt")
    calendar_dates_path = os.path.join(gtfs_dir, "calendar_dates.txt")

    calendar_df = pd.read_csv(calendar_path, dtype=str).rename(
        columns=lambda c: c.strip()
    )
    calendar_dates_df = pd.read_csv(calendar_dates_path, dtype=str).rename(
        columns=lambda c: c.strip()
    )

    daily_schedules = []
    for date in dates:
        target_date = pd.to_datetime(date).date()

        active_services = service_ids_for_date(
            calendar_df, calendar_dates_df, target_date
        )

        print(f"Active services for {date}: {active_services}")

        trips = trips_immutable.copy()
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
        daily_schedule = build_merged_df(
            stop_times, stops, routes, trips, date, agency_tz
        )
        daily_schedules.append(daily_schedule)
    return pd.concat(daily_schedules, ignore_index=True)


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Correlate bus location data with GTFS scheduled stops"
    )
    parser.add_argument(
        "--gtfs-dir",
        required=True,
        help="Path to the GTFS directory containing extracted GTFS files",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the output parquet and CSV files (with no extension)",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Target date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="Target date in YYYY-MM-DD format",
    )

    args = parser.parse_args()
    dates = [
        date.strftime("%Y-%m-%d")
        for date in pd.date_range(start=args.start_date, end=args.end_date)
    ]
    schedule = build_full_schedule(args.gtfs_dir, dates)
    schedule.to_parquet(f"{args.output}.parquet")
    schedule.to_csv(f"{args.output}_debug.csv", index=False)
