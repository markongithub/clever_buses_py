from enum import Enum
import sys
import pandas as pd

EASTERN_LINE = -76.15868904560217
WESTERN_LINE = -76.20110727999335
STATE_FAIR_HEADSIGN = "901 State Fair - Hub"


class FairState(Enum):
    GOING_TO_FAIR = 0
    COMING_FROM_FAIR = 1
    UNCLEAR = 2


def fair_state_from_lon(lon):
    if lon < WESTERN_LINE:
        return FairState.COMING_FROM_FAIR
    elif lon > EASTERN_LINE:
        return FairState.GOING_TO_FAIR
    else:
        return FairState.UNCLEAR


input_file = sys.argv[1]
df = pd.read_parquet(input_file)

current_trip = None
started_at = None
last_timestamp = None
output_trips = []
current_fair_state = FairState.UNCLEAR

# I can't filter on the 901 bus here, because I need to know when a bus stops
# being the 901 and break the trip there.
for name, group in df.groupby("id"):
    for _, row in group.iterrows():
        # Both op and rt seem to get reset randomly. These elements form what I
        # think is the unique ID of a trip.
        this_trip = {k: row[k] for k in ["fs", "id"]}
        this_coords = "{lat},{lon}".format(lat=row["lat"][:7], lon=row["lon"][:7])
        print(
            f'{row["retrieved_at"]}: bus {row["id"]} was seen with head sign {row["fs"]} at {this_coords}'
        )
        # When the head sign is "N/A", the dd changes a lot, so we have to ignore
        # those as unique trips.
        if current_trip != this_trip and this_trip["fs"] != "N/A":
            print(f"Starting new trip: {this_trip}")
            current_trip = this_trip
            last_fair_state = FairState.UNCLEAR
        # Here's where our special treatment of the state fair buses happens.
        if this_trip["fs"] == STATE_FAIR_HEADSIGN:
            current_fair_state = fair_state_from_lon(float(row["lon"]))
            if (
                current_fair_state == FairState.COMING_FROM_FAIR
                and last_fair_state == FairState.GOING_TO_FAIR
            ):
                difference = row["retrieved_at"] - fair_started_at
                print(
                    f'{fair_started_at}: bus {row["id"]} begins a fairgrounds-bound trip on the {row["fs"]} route arriving {difference} later at {row["retrieved_at"]}'
                )
            elif (
                current_fair_state == FairState.GOING_TO_FAIR
                and last_fair_state == FairState.COMING_FROM_FAIR
            ):
                difference = row["retrieved_at"] - fair_started_at
                print(
                    f'{fair_started_at}: bus {row["id"]} leaves the fairgrounds on the {row["fs"]} route arriving {difference} later at {row["retrieved_at"]}'
                )
            elif current_fair_state == FairState.UNCLEAR:
                current_fair_state = last_fair_state
            if current_fair_state != last_fair_state:
                fair_started_at = row["retrieved_at"]

        last_timestamp = row["retrieved_at"]
        last_coords = this_coords
        last_fair_state = current_fair_state
