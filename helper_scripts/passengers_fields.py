import pandas as pd
import os
import numpy as np
\
# API to db
# import urllib
# url = 'https://data.gov.il/api/3/action/datastore_search?resource_id=e6cfac2f-979a-44fd-b439-ecb116ec0b16&limit=5&q=title:jones'  
# fileobj = urllib.request.urlopen(url)
# print(fileobj.read())
      
base_path = r"C:\Users\User\Documents\INSPECTRA\Data"
gtfs_path = os.path.join(base_path, "tlv_busses_gtfs_extract")

# Load GTFS files
trips = pd.read_csv(os.path.join(gtfs_path, 'trips.txt'))
stops = pd.read_csv(os.path.join(gtfs_path, 'stops.txt'))
stop_times = pd.read_csv(os.path.join(gtfs_path, 'stop_times.txt'))
routes = pd.read_csv(os.path.join(gtfs_path, 'routes.txt'))
agency = pd.read_csv(os.path.join(gtfs_path, 'agency.txt'))

# Load other CSV files
b2 = pd.read_csv(os.path.join(base_path, 'b2.csv'), delimiter='|')
e6 = pd.read_csv(os.path.join(base_path, 'e6.csv'), delimiter='\t')
e7 = pd.read_csv(os.path.join(base_path, 'e7.csv'), delimiter='|')

# Process b2.csv - stop boarders
day_cols = [col for col in b2.columns if col.lower().startswith('day')]
b2[day_cols] = b2[day_cols].replace('', 0).fillna(0)
b2[day_cols] = b2[day_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
b2['total_boarders'] = b2[day_cols].sum(axis=1)
b2 = b2.rename(columns={'StationId': 'stop_id'})
b2['stop_id'] = b2['stop_id'].astype(int)
b2 = b2.merge(stops[['stop_id', 'stop_name']], on='stop_id', how='left')

# Process e7.csv - payments
e7_day_cols = [col for col in e7.columns if col.startswith('D')]
e7[e7_day_cols] = e7[e7_day_cols].replace('', 0).fillna(0)
e7[e7_day_cols] = e7[e7_day_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
e7['total_paid'] = e7[e7_day_cols].sum(axis=1)

payment_agg = e7.groupby(['OperatorLineId', 'Direction'], as_index=False)['total_paid'].sum()

# Sum boarders per stop (station output)
station_output = b2.groupby(['stop_id', 'stop_name']).agg({'total_boarders': 'sum'}).reset_index()
station_output = station_output.rename(columns={
    'stop_id': 'StationID',
    'stop_name': 'StationName',
    'total_boarders': 'Boarders'
})
station_output['Paid'] = np.nan
station_output['NotPaid'] = np.nan

# --- Map boarders to trips ---
stop_times = stop_times.merge(b2[['stop_id', 'total_boarders']], on='stop_id', how='left')
boarders_per_trip = stop_times.groupby('trip_id')['total_boarders'].sum().reset_index()

# Fix types to string to avoid merge errors
trips['trip_id'] = trips['trip_id'].astype(str)
boarders_per_trip['trip_id'] = boarders_per_trip['trip_id'].astype(str)
payment_agg['OperatorLineId'] = payment_agg['OperatorLineId'].astype(str)

# Add operator line and direction info to trips to enable grouping
# This assumes trips.txt has a column for operator line or route_id linking to e7 OperatorLineId
# Let's assume trips.route_id corresponds to OperatorLineId:
trips['route_id'] = trips['route_id'].astype(str)
payment_agg['OperatorLineId'] = payment_agg['OperatorLineId'].astype(str)

# Aggregate trips by route_id and direction (from trips.direction_id)
trip_boarders_agg = trips[['trip_id', 'route_id', 'direction_id']].merge(boarders_per_trip, on='trip_id', how='left')
trip_boarders_agg['total_boarders'] = trip_boarders_agg['total_boarders'].fillna(0)

# Merge payment data per route + direction
trip_boarders_agg = trip_boarders_agg.merge(payment_agg,
                                            left_on=['route_id', 'direction_id'],
                                            right_on=['OperatorLineId', 'Direction'],
                                            how='left')

trip_boarders_agg['total_paid'] = trip_boarders_agg['total_paid'].fillna(0)

# Calculate total boarders per route_id + direction to get proportions
route_dir_totals = trip_boarders_agg.groupby(['route_id', 'direction_id'])['total_boarders'].transform('sum')

# Avoid division by zero
route_dir_totals = route_dir_totals.replace(0, np.nan)

# Allocate paid proportionally to boarders per trip
trip_boarders_agg['paid_allocated'] = trip_boarders_agg['total_paid'] * (trip_boarders_agg['total_boarders'] / route_dir_totals)
trip_boarders_agg['paid_allocated'] = trip_boarders_agg['paid_allocated'].fillna(0)

# Calculate NotPaid
trip_boarders_agg['not_paid'] = trip_boarders_agg['total_boarders'] - trip_boarders_agg['paid_allocated']
trip_boarders_agg.loc[trip_boarders_agg['not_paid'] < 0, 'not_paid'] = 0

# Final trip output
trip_output = trip_boarders_agg.rename(columns={
    'trip_id': 'TripID',
    'direction_id': 'Direction',
    'total_boarders': 'Boarders',
    'paid_allocated': 'Paid',
    'not_paid': 'NotPaid'
})

trip_output = trip_output[['TripID', 'Direction', 'Paid', 'Boarders', 'NotPaid']]

# Save outputs
station_output.to_csv(os.path.join(base_path, 'station_output.csv'), index=False, encoding='utf-8-sig')
trip_output.to_csv(os.path.join(base_path, 'trip_output.csv'), index=False, encoding='utf-8-sig')

print("station_output.csv and trip_output.csv generated successfully.")
