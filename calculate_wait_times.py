import sys
import numpy as np
import pandas as pd


def generate_wait_times(relevant_timestamps, route_direction, last_trip):
    for timestamp in relevant_timestamps:
        new_row = {
            "route_direction": route_direction,
            "time": timestamp,
            # time_since_last_departure / np.timedelta64(1,'m')
            "wait_time": (timestamp - last_trip) / np.timedelta64(1, "m"),
        }
        yield new_row


def generate_wait_times_df(trips_df, early_bound, late_bound):
    timestamps = pd.date_range(early_bound, late_bound, freq="1min")

    rows = []
    for route_direction, group in trips_df.query(
        "start_time >= @early_bound and start_time <= @late_bound"
    ).groupby(["route_name", "direction"]):
        last_trip = timestamps[0]
        for _, row in group.iterrows():
            next_trip = row["start_time"]
            relevant_timestamps = timestamps[
                (timestamps >= last_trip) & (timestamps <= next_trip)
            ]
            rows += generate_wait_times(relevant_timestamps, route_direction, last_trip)
            last_trip = next_trip
        relevant_timestamps = timestamps[(timestamps >= last_trip)]
        rows += generate_wait_times(relevant_timestamps, route_direction, last_trip)

    output = pd.DataFrame(rows)
    return output


def main():
    df = pd.read_parquet(sys.argv[1])

    early_bound = "2024-08-27 12:45"
    late_bound = "2024-08-28 00:45"

    output = generate_wait_times_df(df, early_bound, late_bound)
    print(output)


if __name__ == "__main__":
    main()
