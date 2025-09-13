from enum import Enum

import pytz
import sys
import pandas as pd

HUB_HEAD_SIGN = "901 State Fair - Hub"
DESTINY_HEAD_SIGN = "909 Destiny USA"
LONG_BRANCH_HEAD_SIGN = "907 Long Branch Park"
ALL_HEAD_SIGNS = [HUB_HEAD_SIGN, DESTINY_HEAD_SIGN, LONG_BRANCH_HEAD_SIGN]
input_file = sys.argv[1]
output_file = sys.argv[2]
df = pd.read_parquet(input_file)

df["retrieved_at"].dt.tz_localize("utc")


def format_time(whatever_time):
    return whatever_time.tz_localize("utc").astimezone(pytz.timezone("US/Eastern"))


def is_state_fair_hours(timestamp):
    if timestamp.year != 2025:
        raise ValueError("this script is hard-coded for 2025 data, sorry")
    if timestamp.month not in [8, 9]:
        return False
    if timestamp.month == 8 and timestamp.day < 20:
        return False
    if timestamp.month == 9 and timestamp.day > 2:
        return False
    if timestamp.hour > 2 and timestamp.hour < 12:
        return False
    if timestamp.hour == 12 and timestamp.minute < 45:
        return False
    if timestamp.month == 8 and timestamp.day == 20 and timestamp.hour < 12:
        return False
    if timestamp.month == 9 and timestamp.day == 2 and timestamp.hour > 2:
        return False
    if (
        (timestamp.month == 8 and timestamp.day == 30)
        or (timestamp.month == 9 and timestamp.day == 1)
    ) and (timestamp.hour > 2 and timestamp.hour < 15):
        return False
    return True


rows = []
count = 0
for retrieved_at, group in df.groupby("retrieved_at"):
    if not is_state_fair_hours(retrieved_at):
        continue
    current_buses_by_route = {head_sign: set() for head_sign in ALL_HEAD_SIGNS}
    for _, row in group.iterrows():
        head_sign = row["fs"]
        if head_sign not in ALL_HEAD_SIGNS:
            continue
        bus_id = row["id"]
        if head_sign in current_buses_by_route:
            current_buses_by_route[head_sign].add(bus_id)
        else:
            raise ("This should never happen anymore")
            current_buses_by_route[head_sign] = set([bus_id])
        # print(f"current buses by route: {current_buses_by_route}")
    current_counts_by_route = {
        head_sign: len(current_buses_by_route[head_sign])
        for head_sign in current_buses_by_route
    }
    for route in current_counts_by_route:
        new_row = {
            "timestamp": retrieved_at,
            "route": route,
            "count": current_counts_by_route[route],
        }
        rows.append(new_row)
        count += 1

output = pd.DataFrame(rows)
print(output)  # This will only be a summary with sample rows
output.to_parquet(output_file)
