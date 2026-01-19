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


def fix_headsign_for_gtfs(position_dict):
    if (
        position_dict["fs"] == "220 James St - Molloy Rd - Airpark"
        and position_dict["dd"] == "TO HUB"
    ):
        return "220 James St - To Hub"
    return CLEVER_TO_GTFS_SIGN_MISMATCHES.get(position_dict["fs"], position_dict["fs"])


def best_row_for_observation(
    merged_df, stop_id, headsign, retrieved_at, window, previous_observation
):
    candidates = merged_df.loc[
        (merged_df["stop_id"] == stop_id) & (merged_df["trip_headsign"] == headsign)
    ].copy()
    # print(f"Candidates: {candidates}")
    if candidates.empty:
        print(f"No candidates for {headsign} near {stop_id} at {retrieved_at}")
        return None

    # arrival_dt is tz-aware UTC; compute absolute time diff
    candidates["dt_abs"] = (candidates["arrival_dt"] - retrieved_at).abs()
    if previous_observation is not None:
        candidates_same_trip = candidates.loc[
            candidates["trip_id"] == previous_observation["trip_id"]
        ]
        if not candidates_same_trip.empty:
            return candidates_same_trip["dt_abs"].idxmin()
        # print(
        #    f"This bus was on {previous_observation['trip_id']} before but we don't have a candidate on that one."
        # )
        # TODO: Do this for block_id as well.
    # TODO: We could make this window flexible if we know a bus is already running very late.
    within = candidates.loc[candidates["dt_abs"] <= window]
    # print(f"within: {within}")
    if within.empty:
        # print("Fucked.")
        return None
    best_index = within["dt_abs"].idxmin()
    return best_index


def estimate_intermediate_stops(
    merged_df,
    trip_id,
    gtfs_date,
    prev_stop_seq,
    current_stop_seq,
    prev_time,
    current_time,
    bus_id,
):
    """
    Estimate arrival times for stops between prev_stop_seq and current_stop_seq
    on the same trip using linear interpolation based on shape_dist_traveled.
    """
    # Find all stops on this trip between the two observations
    trip_mask = (
        (merged_df["trip_id"] == trip_id)
        & (merged_df["gtfs_date"] == gtfs_date)
        & (merged_df["stop_sequence"] > prev_stop_seq)
        & (merged_df["stop_sequence"] < current_stop_seq)
    )
    intermediate_stops = merged_df.loc[trip_mask].copy()

    if intermediate_stops.empty:
        return

    # Get shape_dist_traveled for interpolation if available
    prev_stop_mask = (
        (merged_df["trip_id"] == trip_id)
        & (merged_df["gtfs_date"] == gtfs_date)
        & (merged_df["stop_sequence"] == prev_stop_seq)
    )
    current_stop_mask = (
        (merged_df["trip_id"] == trip_id)
        & (merged_df["gtfs_date"] == gtfs_date)
        & (merged_df["stop_sequence"] == current_stop_seq)
    )

    prev_indices = merged_df.index[prev_stop_mask]
    current_indices = merged_df.index[current_stop_mask]

    if prev_indices.empty or current_indices.empty:
        return

    prev_idx = prev_indices[0]
    current_idx = current_indices[0]

    prev_dist = merged_df.at[prev_idx, "shape_dist_traveled"]
    current_dist = merged_df.at[current_idx, "shape_dist_traveled"]

    # Use shape_dist_traveled if available, otherwise use stop_sequence
    use_distance = (
        pd.notna(prev_dist)
        and pd.notna(current_dist)
        and float(current_dist) > float(prev_dist)
    )

    time_diff = (current_time - prev_time).total_seconds()

    for idx in intermediate_stops.index:
        # Only estimate if not already observed
        if pd.isna(merged_df.at[idx, "observed_at"]) and pd.isna(
            merged_df.at[idx, "estimated_at"]
        ):
            if use_distance:
                # Interpolate based on distance
                stop_dist = float(merged_df.at[idx, "shape_dist_traveled"])
                dist_ratio = (stop_dist - float(prev_dist)) / (
                    float(current_dist) - float(prev_dist)
                )
            else:
                # Interpolate based on stop sequence
                stop_seq = merged_df.at[idx, "stop_sequence"]
                dist_ratio = (stop_seq - prev_stop_seq) / (
                    current_stop_seq - prev_stop_seq
                )

            estimated_time = prev_time + pd.Timedelta(seconds=time_diff * dist_ratio)
            merged_df.at[idx, "estimated_at"] = estimated_time
            merged_df.at[idx, "late"] = int(
                (estimated_time - merged_df.at[idx, "arrival_dt"]).total_seconds()
            )
            merged_df.at[idx, "bus_id"] = bus_id


def correlate(
    buses_parquet,
    gtfs_dir,
    output_filename_base,
    full_schedule_df,
    time_window_minutes=15,
):
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
    merged = full_schedule_df
    # build stop index using workspace class
    stop_index = StopIndex(stops_path)
    window = pd.Timedelta(minutes=time_window_minutes)

    total_bus_rows = len(buses)
    buses_processed = 0
    stop_ids_cache = {}
    # Track previous observations for each bus to enable interpolation
    bus_last_observation = {}
    for _, r in buses.iterrows():
        buses_processed += 1
        if buses_processed % OUTPUT_FREQUENCY == 0:
            print(f"Processed {buses_processed}/{total_bus_rows}...")
        lat = float(r.get("lat", np.nan))
        lon = float(r.get("lon", np.nan))
        if pd.isna(lat) or pd.isna(lon):
            print("No lat/lon, nothing we can do here.")
            continue
        # if r.get("id") not in ["1750", "1760"]:
        #    continue
        if r.get("rt") != CLEVER_ROUTE_ID:
            continue
        # print(r.to_dict())
        fixed_headsign = fix_headsign_for_gtfs(r)
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
            # Check if we have a previous observation for this bus
        bus_key = r["id"]
        previous_observation = bus_last_observation.get(bus_key)
        best_index = best_row_for_observation(
            merged, stop_id, fixed_headsign, retrieved_at, window, previous_observation
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
            merged.at[best_index, "estimated_at"] = retrieved_at

            merged.at[best_index, "bus_id"] = r["id"]
            merged.at[best_index, "lat"] = lat
            merged.at[best_index, "lon"] = lon
            late = int(
                (retrieved_at - merged.at[best_index, "arrival_dt"]).total_seconds()
            )
            merged.at[best_index, "late"] = late

            # Get trip info for this observation
            trip_id = merged.at[best_index, "trip_id"]
            gtfs_date = merged.at[best_index, "gtfs_date"]
            current_stop_seq = merged.at[best_index, "stop_sequence"]

            # print(
            #    f"I think bus {bus_key} is on trip {trip_id} and {late} seconds late."
            # )
            if previous_observation is not None:
                previous_observation = bus_last_observation[bus_key]
                # Only interpolate if it's the same trip and date
                if (
                    previous_observation["trip_id"] == trip_id
                    and previous_observation["gtfs_date"] == gtfs_date
                ):
                    if current_stop_seq > previous_observation["stop_sequence"]:
                        # print(
                        #    f"Want to estimate intermediate stops for bus {bus_key} between {previous_observation['time']} and {retrieved_at}..."
                        # )
                        estimate_intermediate_stops(
                            merged,
                            trip_id,
                            gtfs_date,
                            previous_observation["stop_sequence"],
                            current_stop_seq,
                            previous_observation["time"],
                            retrieved_at,
                            bus_key,
                        )

            # Update the last observation for this bus
            bus_last_observation[bus_key] = {
                "trip_id": trip_id,
                "gtfs_date": gtfs_date,
                "stop_sequence": current_stop_seq,
                "time": retrieved_at,
            }

        else:
            recorded_bus = merged.at[best_index, "bus_id"]
            if recorded_bus == r["id"]:
                # print(
                #    f"Bus {r['id']} with head sign {r['fs']} was already at {nearest['stop_name']} so we won't edit the arrival data."
                # )
                pass
            else:
                print(
                    f"Uh oh. We saw bus {recorded_bus} at {nearest['stop_name']} at {merged.at[best_index, 'observed_at']} with head sign {r['fs']} but at {retrieved_at} we have {r['id']}"
                )
    summarize_findings(merged)
    merged.to_parquet(f"{output_filename_base}.parquet")
    merged.to_csv(f"{output_filename_base}_debug.csv", index=False)


def summarize_findings(stop_times_merged_df):
    """
    Summarize correlation findings by counting trips with and without observed_at data.
    """
    # Group by trip_id to analyze at the trip level
    trip_groups = stop_times_merged_df.groupby(["gtfs_date", "trip_id"])

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
    estimated_stops = stop_times_merged_df["estimated_at"].notna().sum()
    unobserved_stops = total_stops - estimated_stops

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
            stop_times_merged_df.set_index(["gtfs_date", "trip_id"]).index.isin(
                trips_without_obs_ids
            )
        ].copy()
        # Get first stop for each trip (sorted by stop_sequence)
        first_stops = (
            unobserved_trips.sort_values("stop_sequence")
            .groupby(["gtfs_date", "trip_id"])
            .first()
            .reset_index()
        )

        # Sort by departure time
        first_stops = first_stops.sort_values("arrival_dt")

        for _, trip in first_stops.iterrows():
            gtfs_date = trip["gtfs_date"]
            trip_id = trip["trip_id"]
            headsign = trip.get("trip_headsign", "Unknown")
            departure = trip["arrival_dt"]
            block = trip["block_id"]
            print(
                f" {gtfs_date} {trip_id} from block {block}: {headsign} @ {departure}"
            )

    print("=" * 60 + "\n")
    print(f"Stop-level statistics:")
    print(f"  Total scheduled stops: {total_stops}")
    print(
        f"  Stops with observations: {observed_stops} ({observed_stops/total_stops*100:.1f}%)"
    )
    print(
        f"  Stops with data (observed or estimated): {estimated_stops} ({estimated_stops/total_stops*100:.1f}%)"
    )
    print(
        f"  Stops without data: {unobserved_stops} ({unobserved_stops/total_stops*100:.1f}%)"
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
        help="Path to the GTFS directory containing extracted GTFS files (only for stop lat/lon)",
    )
    parser.add_argument(
        "--schedule",
        required=True,
        help="Path to the schedule parquet file (no extension, sorry)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=20,
        help="Time window in minutes for matching (default: 20)",
    )

    args = parser.parse_args()

    full_schedule_df = pd.read_parquet(f"{args.schedule}.parquet")

    correlate(
        args.buses,
        args.gtfs_dir,
        args.schedule,
        full_schedule_df,
        time_window_minutes=args.window,
    )
