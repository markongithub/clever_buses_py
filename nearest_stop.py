import sys
import pandas as pd
from sortedcontainers import SortedList
from math import radians, cos, sin, asin, sqrt


def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance in kilometers between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of earth in kilometers. Use 3956 for miles. Determines return value units.
    return c * r


TEST_COORDS = (43.0614, -76.059)
LAT_RADIUS = 0.005
LON_RADIUS = 0.012


def get_stop_lat(row):
    return row["stop_lat"]


def get_stop_lon(row):
    return row["stop_lon"]


class StopIndex:
    def __init__(self, stops_csv_path):
        self.lat_index = SortedList([], key=get_stop_lat)
        for _, row in pd.read_csv(stops_csv_path).iterrows():
            self.lat_index.add(row)

    def find_stop(self, lat, lon):
        best_distance = 99999
        best_stop = None
        stops_checked = 0
        stops_checked_haversine = 0
        for stop in self.lat_index.irange(
            minimum={"stop_lat": lat - LAT_RADIUS},
            maximum={"stop_lat": lat + LAT_RADIUS},
        ):
            stops_checked += 1
            if abs(stop["stop_lon"] - lon) <= LON_RADIUS:
                stops_checked_haversine += 1
                distance = haversine(lat, lon, stop["stop_lat"], stop["stop_lon"])
                # print(f"{stop['stop_name']} is {distance} away from my goal.")
                if best_stop is None or distance < best_distance:
                    best_distance = distance
                    best_stop = stop["stop_name"]
        # print(
        #    f"We considered {stops_checked} stops and calculated {stops_checked_haversine} distances."
        # )
        # if best_stop:
        #    print(f"Best guess for this stop: {best_stop}, {best_distance} km away.")
        # else:
        #    print("We didn't find any good candidates for this stop.")
        return best_stop


def main():
    stop_index = StopIndex(sys.argv[1])
    test_lat, test_lon = TEST_COORDS
    best_stop = stop_index.find_stop(test_lat, test_lon)


if __name__ == "__main__":
    main()
