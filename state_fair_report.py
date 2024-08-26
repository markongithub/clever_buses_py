from enum import Enum

import pytz
import sys
import pandas as pd

HUB_EASTERN_LINE = -76.15868904560217
HUB_WESTERN_LINE = -76.20110727999335
HUB_HEAD_SIGN = "901 State Fair - Hub"
DESTINY_EASTERN_LINE = -76.176634
DESTINY_WESTERN_LINE = HUB_WESTERN_LINE
DESTINY_HEAD_SIGN = "909 Destiny USA"
LONG_BRANCH_HEAD_SIGN = "907 Long Branch Park"
LONG_BRANCH_COORDS = (43.11092841942912, -76.26195936251607)
LONG_BRANCH_EASTERN_LINE = -76.22599168015266


class FairState(Enum):
    GOING_TO_FAIR = 0
    COMING_FROM_FAIR = 1
    UNCLEAR = 2


def figure_fair_state(head_sign, lat, lon):
    if head_sign == HUB_HEAD_SIGN:
        if lon < HUB_WESTERN_LINE:
            return FairState.COMING_FROM_FAIR
        elif lon > HUB_EASTERN_LINE:
            return FairState.GOING_TO_FAIR
        else:
            return FairState.UNCLEAR
    if head_sign == DESTINY_HEAD_SIGN:
        if lon < DESTINY_WESTERN_LINE:
            return FairState.COMING_FROM_FAIR
        elif lon > DESTINY_EASTERN_LINE:
            return FairState.GOING_TO_FAIR
        else:
            return FairState.UNCLEAR
    if head_sign == LONG_BRANCH_HEAD_SIGN:
        if lon > LONG_BRANCH_EASTERN_LINE:
            return FairState.COMING_FROM_FAIR
        # if you're north AND east of LONG_BRANCH_COORDS, you've reached the Long Branch Park terminus
        elif lat > LONG_BRANCH_COORDS[0] and lon > LONG_BRANCH_COORDS[1]:
            return FairState.GOING_TO_FAIR
        else:
            return FairState.UNCLEAR
    raise(Exception(f"I don't know how to handle the route {head_sign}"))


input_file = sys.argv[1]
df = pd.read_parquet(input_file)

current_trip = None
started_at = None
last_timestamp = None
output_trips = []
current_fair_state = FairState.UNCLEAR


df["retrieved_at"].dt.tz_localize("utc")


def format_direction(route_name, direction):
    if direction == FairState.GOING_TO_FAIR:
        return "Fairgrounds-bound"
    if route_name == HUB_HEAD_SIGN:
        return "hub-bound"
    if route_name == DESTINY_HEAD_SIGN:
        return "Destiny USA-bound"
    if route_name == LONG_BRANCH_HEAD_SIGN:
        return "Long Branch Park-bound"
    else:
        raise(Exception(
            f"I don't know how to format direction {direction} and route {route_name}"
        ))


def format_duration(tdelta):
    hours, rem = divmod(tdelta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    hmmss = f"{hours}h{str(minutes).zfill(2)}m{str(seconds).zfill(2)}s"
    if tdelta.days:
        return f"{tdelta.days} days, {hmmss} (this is obviously an error)"
    else:
        return hmmss


def format_trip(start_time, end_time, bus_id, route_name, direction):
    difference = row["retrieved_at"] - fair_started_at
    direction_formatted = format_direction(route_name, direction)
    return f'{start_time.tz_localize("utc").astimezone(pytz.timezone("US/Eastern"))}: bus {bus_id} begins a {direction_formatted} trip on the {route_name} route arriving at {end_time.tz_localize("utc").astimezone(pytz.timezone("US/Eastern"))} (duration {format_duration(difference)})'


# I can't filter on the 901 bus here, because I need to know when a bus stops
# being the 901 and break the trip there.
for name, group in df.groupby("id"):
    for _, row in group.iterrows():
        # Both op and rt seem to get reset randomly. These elements form what I
        # think is the unique ID of a trip.
        this_trip = {k: row[k] for k in ["fs", "id"]}
        this_coords = "{lat},{lon}".format(lat=row["lat"][:7], lon=row["lon"][:7])
        #        print(
        #            f'{row["retrieved_at"]}: bus {row["id"]} was seen with head sign {row["fs"]} at {this_coords}'
        #        )
        # When the head sign is "N/A", the dd changes a lot, so we have to ignore
        # those as unique trips.
        if current_trip != this_trip and this_trip["fs"] != "N/A":
            #            print(f"Starting new trip: {this_trip}")
            current_trip = this_trip
            last_fair_state = FairState.UNCLEAR
        # Here's where our special treatment of the state fair buses happens.
        if this_trip["fs"] in [HUB_HEAD_SIGN, DESTINY_HEAD_SIGN, LONG_BRANCH_HEAD_SIGN]:
            current_fair_state = figure_fair_state(
                this_trip["fs"], float(row["lat"]), float(row["lon"])
            )
            if (
                current_fair_state == FairState.COMING_FROM_FAIR
                and last_fair_state == FairState.GOING_TO_FAIR
            ):
                print(
                    format_trip(
                        fair_started_at,
                        row["retrieved_at"],
                        row["id"],
                        row["fs"],
                        last_fair_state,
                    )
                )
            elif (
                current_fair_state == FairState.GOING_TO_FAIR
                and last_fair_state == FairState.COMING_FROM_FAIR
            ):
                print(
                    format_trip(
                        fair_started_at,
                        row["retrieved_at"],
                        row["id"],
                        row["fs"],
                        last_fair_state,
                    )
                )
            elif current_fair_state == FairState.UNCLEAR:
                current_fair_state = last_fair_state
            if current_fair_state != last_fair_state:
                fair_started_at = row["retrieved_at"]

        last_timestamp = row["retrieved_at"]
        last_coords = this_coords
        last_fair_state = current_fair_state
