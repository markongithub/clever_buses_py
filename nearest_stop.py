import pandas as pd
from sortedcontainers import SortedList

def main():
    df = pd.read_csv(sys.argv[1])

    sl = SortedList(key=lambda r: r["stop_lat"])
    for _, row in df.iterrows():
	sl.add(r)

    for stop in sl.irange(minimum=43.065120, maximum=43.065130):
        print(stop["stop_name"])


if __name__ == "__main__":
    main()


