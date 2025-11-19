import sys
import pandas as pd
from sortedcontainers import SortedList
from math import radians, cos, sin, asin, sqrt
from functools import lru_cache


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
DEFAULT_LAT_RADIUS = 0.005
DEFAULT_LON_RADIUS = 0.012


def get_stop_lat(row):
    return row["stop_lat"]


def get_stop_lon(row):
    return row["stop_lon"]


class StopIndex:
    def __init__(
        self,
        stops_csv_path,
        lat_radius=DEFAULT_LAT_RADIUS,
        lon_radius=DEFAULT_LON_RADIUS,
    ):
        self.lat_index = SortedList([], key=get_stop_lat)
        for _, row in pd.read_csv(stops_csv_path).iterrows():
            self.lat_index.add(row)
        self.lat_radius = lat_radius
        self.lon_radius = lon_radius

    @lru_cache
    def find_candidates(self, lat, lon, limit_set=None):
        stops_checked = 0
        stops_checked_haversine = 0
        candidates = []

        latitude_candidates = self.lat_index.irange(
            minimum={"stop_lat": lat - self.lat_radius},
            maximum={"stop_lat": lat + self.lat_radius},
        )
        for stop in latitude_candidates:
            if limit_set and str(stop["stop_id"]) not in limit_set:
                # print(f"{stop['stop_id']} is not in {limit_set}")
                continue
            stops_checked += 1
            if abs(stop["stop_lon"] - lon) <= self.lon_radius:
                stops_checked_haversine += 1
                distance = haversine(lat, lon, stop["stop_lat"], stop["stop_lon"])
                # print(f"{stop['stop_name']} is {distance} away from my goal.")
                stop["distance"] = distance
                candidates.append(stop)
        return sorted(candidates, key=lambda d: d["distance"])

    @lru_cache
    def find_stop(self, lat, lon, limit_set=None):
        candidates = self.find_candidates(lat, lon, limit_set)
        if candidates:
            return candidates[0]
        return None


def main():
    stop_index = StopIndex(sys.argv[1])
    test_lat, test_lon = TEST_COORDS
    best_stop = stop_index.find_stop(test_lat, test_lon)


if __name__ == "__main__":
    main()
