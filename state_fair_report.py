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
    raise (Exception(f"I don't know how to handle the route {head_sign}"))


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
        raise (
            Exception(
                f"I don't know how to format direction {direction} and route {route_name}"
            )
        )


def format_duration(tdelta):
    hours, rem = divmod(tdelta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    hmmss = f"{hours}h{str(minutes).zfill(2)}m{str(seconds).zfill(2)}s"
    if tdelta.days:
        return f"{tdelta.days} days, {hmmss} (this is obviously an error)"
    else:
        return hmmss


def format_trip(trip):
    difference = trip["end_time"] - trip["start_time"]
    return f'{trip["start_time"].tz_localize("utc").astimezone(pytz.timezone("US/Eastern"))}: bus {trip["bus_id"]} begins a {trip["direction"]} trip on the {trip["route_name"]} route arriving at {trip["end_time"].tz_localize("utc").astimezone(pytz.timezone("US/Eastern"))} (duration {format_duration(difference)})'


def trip_dict(start_time, end_time, bus_id, route_name, direction):
    return {
        "start_time": start_time,
        "end_time": end_time,
        "bus_id": bus_id,
        "route_name": route_name,
        "direction": format_direction(route_name, direction),
    }


def separate_trips(df):
    output_trips = []
    df["retrieved_at"].dt.tz_localize("utc")

    # I can't filter on the 901 bus here, because I need to know when a bus stops
    # being the 901 and break the trip there.
    for name, group in df.groupby("id"):
        current_trip = None
        started_at = None
        last_timestamp = None
        current_fair_state = FairState.UNCLEAR
        last_assumed_head_sign = None
        for _, row in group.iterrows():
            # print(f"row: {row}")
            # The head sign seems to turn to "N/A" at random times, while the bus continues on its route,
            # so when we see N/A let's assume we're still on the last one.
            if row["fs"] == "N/A":
                assumed_head_sign = last_assumed_head_sign
            else:
                assumed_head_sign = row["fs"]
            this_trip = {"fs": assumed_head_sign, "id": row["id"]}
            this_coords = "{lat},{lon}".format(lat=row["lat"][:7], lon=row["lon"][:7])
            # print(
            #    f"{row['retrieved_at']}: bus {row['id']} was seen with rt {row['rt']} and head sign {row['fs']} at {this_coords}"
            # )
            if current_trip != this_trip:
                current_trip = this_trip
                last_fair_state = FairState.UNCLEAR
            # Here's where our special treatment of the state fair buses happens.
            if assumed_head_sign in [
                HUB_HEAD_SIGN,
                DESTINY_HEAD_SIGN,
                LONG_BRANCH_HEAD_SIGN,
            ]:
                current_fair_state = figure_fair_state(
                    assumed_head_sign, float(row["lat"]), float(row["lon"])
                )
                # print(f"current_fair_state is now {current_fair_state}")
                if (
                    current_fair_state != last_fair_state
                    and current_fair_state != FairState.UNCLEAR
                    and last_fair_state != FairState.UNCLEAR
                ):
                    # should this be a generator?
                    output_trips.append(
                        trip_dict(
                            fair_started_at,
                            row["retrieved_at"],
                            row["id"],
                            assumed_head_sign,
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
            last_assumed_head_sign = assumed_head_sign
    return output_trips


def output_parquet(output_trips, output_filename):
    new_df = pd.DataFrame(output_trips)
    print("Writing out final parquet file...")
    print(new_df.info())
    new_df.to_parquet(output_filename)

    print("Confirming that written file is readable...")
    del [[new_df]]
    is_parquet_valid = pd.read_parquet(output_filename)

    print(f"{len(output_trips)} written to {output_filename}")


def main():
    input_file = sys.argv[1]
    df = pd.read_parquet(input_file)
    output_trips = separate_trips(df)

    if len(sys.argv) > 2:
        output_parquet(output_trips, sys.argv[2])
    else:
        for trip in output_trips:
            print(format_trip(trip))


if __name__ == "__main__":
    main()
