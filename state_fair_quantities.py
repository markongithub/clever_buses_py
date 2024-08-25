from enum import Enum

import pytz
import sys
import pandas as pd

HUB_HEAD_SIGN = "901 State Fair - Hub"
DESTINY_HEAD_SIGN = "909 Destiny USA"
LONG_BRANCH_HEAD_SIGN = "907 Long Branch Park"
ALL_HEAD_SIGNS = [HUB_HEAD_SIGN, DESTINY_HEAD_SIGN, LONG_BRANCH_HEAD_SIGN]
input_file = sys.argv[1]
df = pd.read_parquet(input_file)

started_at = None
previous_timestamp = None
previous_counts_by_route = {}


df['retrieved_at'].dt.tz_localize('utc')

def format_time(whatever_time):
    return whatever_time.tz_localize('utc').astimezone(pytz.timezone('US/Eastern'))

for retrieved_at, group in df.groupby("retrieved_at"):
    current_buses_by_route = {head_sign:set() for head_sign in ALL_HEAD_SIGNS}
    for _, row in group.iterrows():
        head_sign = row['fs']
        if head_sign not in ALL_HEAD_SIGNS:
            continue
        bus_id = row['id']
        if head_sign in current_buses_by_route:
            current_buses_by_route[head_sign].add(bus_id)
        else:
            raise("This should never happen anymore")
            current_buses_by_route[head_sign] = set([bus_id])
#     print(f"current buses by route: {current_buses_by_route}")
    current_counts_by_route = {head_sign:len(current_buses_by_route[head_sign]) for head_sign in current_buses_by_route}
    if current_counts_by_route == previous_counts_by_route:
        pass
    else:
        if started_at:
            # print(f"{format_time(started_at)} to {format_time(previous_timestamp)}: {current_counts_by_route}")
            # this violates every principle ever involved in CSV
            counts_csv = ','.join([str(v) for v in current_counts_by_route.values()])
            print(f"{format_time(started_at)},{counts_csv}")
            print(f"{format_time(previous_timestamp)},{counts_csv}")
        started_at = retrieved_at
        previous_counts_by_route = current_counts_by_route
    previous_timestamp = retrieved_at


    # last_timestamp = row["retrieved_at"]
    # last_coords = this_coords
    # last_fair_state = current_fair_state
