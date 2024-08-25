import sys
import pandas as pd

# eastern line 43.05192154121249, -76.15868904560217
# western line 43.06842055469995, -76.20110727999335

input_file = sys.argv[1]
output_file = sys.argv[2]
df = pd.read_parquet(input_file)

current_trip = None
started_at = None
last_timestamp = None
output_trips = []

# for _, row in df.loc[df['id'] == '1758'].iterrows():
for name, group in df.groupby('id'):
  # if name != '1761':
   # continue
  for _, row in group.iterrows():
    # Both op and rt seem to get reset randomly. These elements form what I
    # think is the unique ID of a trip.
    this_trip = {k: row[k] for k in ['fs', 'dd', 'pid', 'run', 'bid', 'id']}
    this_coords = '{lat},{lon}'.format(lat=row['lat'][:7],lon=row['lon'][:7])
    print(f'{row["retrieved_at"]}: bus {row["id"]} was seen with head sign {row["fs"]} at {this_coords}')
    print(row)
    # When the head sign is "N/A", the dd changes a lot, so we have to ignore
    # those as unique trips.
    if current_trip != this_trip and this_trip['fs'] != 'N/A':
      print(f'Starting new trip: {this_trip}')
      if current_trip and current_trip['fs'] not in ['Not in Service', 'N/A']:
        # print('{start} to {end}: {trip}'.format(trip=current_trip, start=started_at, end=last_timestamp))
        output_trip = current_trip.copy()
        output_trip['first_seen'] = started_at
        output_trip['last_seen'] = last_timestamp
        output_trip['start_coords'] = start_coords
        output_trip['final_coords'] = last_coords
        print(f'finished trip: {output_trip}')
      current_trip = this_trip
      start_coords = this_coords
      started_at = row['retrieved_at']
    last_timestamp = row['retrieved_at']
    last_coords = this_coords

