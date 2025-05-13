import pandas as pd
import zipfile
import os

# Path to your downloaded GTFS zip file
gtfs_zip_path = r"Inspectra\tel_aviv_bus_gtfs (1).zip" # If running on local, change to actual path, example: (C:\Users\Ofek\Is\Very\Cool\tel_aviv_bus_gtfs (1).zip)

# Temporary directory to extract files
extract_dir = "gtfs_extracted"

# Create extraction directory if it doesn't exist
os.makedirs(extract_dir, exist_ok=True)

# Extract only the necessary GTFS files
with zipfile.ZipFile(gtfs_zip_path, 'r') as z:
    gtfs_files = ['routes.txt', 'trips.txt', 'stop_times.txt', 'stops.txt', 'agency.txt']
    for file in gtfs_files:
        if file in z.namelist():
            z.extract(file, path=extract_dir)
        else:
            print(f"Warning: {file} not found in GTFS zip, ofek learn how to download properly")

# Load files into pandas DataFrames
routes_df = pd.read_csv(os.path.join(extract_dir, 'routes.txt'))
trips_df = pd.read_csv(os.path.join(extract_dir, 'trips.txt'))
stop_times_df = pd.read_csv(os.path.join(extract_dir, 'stop_times.txt'))
stops_df = pd.read_csv(os.path.join(extract_dir, 'stops.txt'))
agency_df = pd.read_csv(os.path.join(extract_dir, 'agency.txt'))

# ---------------------- FILTER FOR BUSES ONLY ----------------------
# route_type == 3 means bus, TODO add to documentation
routes_df = routes_df[routes_df['route_type'] == 3]

# for inspectras general knowledge: 8 transport types
# 0: Tram, Streetcar, Light rail
# 1: Subway, Metro
# 2: Rail, trains
# 3: Bus 
# 4: Ferry
# 5: Cable car
# 6: Gondola
# 7: Funicular 


# ---------------------- FILTERING FOR TEL AVIV ----------------------

# 1. Find all stops in Tel Aviv
tel_aviv_stops_df = stops_df[stops_df['stop_name'].str.contains("תל אביב", na=False)]
tel_aviv_stop_ids = set(tel_aviv_stops_df['stop_id'])

# 2. Determine first and last stops for each trip
first_stops = stop_times_df.sort_values(['trip_id', 'stop_sequence']).groupby('trip_id').first().reset_index()
last_stops = stop_times_df.sort_values(['trip_id', 'stop_sequence']).groupby('trip_id').last().reset_index()

# 3. Join trip info with first and last stop IDs
trips_with_stops = trips_df.copy()
trips_with_stops = trips_with_stops.merge(first_stops[['trip_id', 'stop_id']], on='trip_id', suffixes=('', '_start'))
trips_with_stops = trips_with_stops.merge(last_stops[['trip_id', 'stop_id']], on='trip_id', suffixes=('', '_end'))

# 4. Keep only trips that start and end in Tel Aviv
trips_in_tel_aviv = trips_with_stops[
    (trips_with_stops['stop_id'].isin(tel_aviv_stop_ids)) &
    (trips_with_stops['stop_id_end'].isin(tel_aviv_stop_ids))
]

# 5. Select 100 unique route IDs from bus-only routes
bus_route_ids = set(routes_df['route_id'])
selected_route_ids = trips_in_tel_aviv[
    trips_in_tel_aviv['route_id'].isin(bus_route_ids)
]['route_id'].drop_duplicates().head(100)

#-----DATA SYNC, 6~9 = Filtering based off of the lines found

# 6. Filter trips to those with selected route IDs
filtered_trips_df = trips_df[trips_df['route_id'].isin(selected_route_ids)]

# 7. Filter stop_times to include only relevant trips
filtered_trip_ids = filtered_trips_df['trip_id']
filtered_stop_times_df = stop_times_df[stop_times_df['trip_id'].isin(filtered_trip_ids)]

# 8. Filter stops to include only those used in relevant trips
used_stop_ids = filtered_stop_times_df['stop_id'].unique()
filtered_stops_df = stops_df[stops_df['stop_id'].isin(used_stop_ids)]

# 9. Filter routes to include only selected bus routes
filtered_routes_df = routes_df[routes_df['route_id'].isin(selected_route_ids)]

# ---------------------- OUTPUT OVERVIEW ----------------------

print("\nFiltered Routes (100 Tel Aviv Bus Lines):")
print(filtered_routes_df.head())

print("\nFiltered Trips:")
print(filtered_trips_df.head())

print("\nFiltered Stop Times:")
print(filtered_stop_times_df.head())

print("\nFiltered Stops:")
print(filtered_stops_df.head())

print("\nAgency:")
print(agency_df.head())

# ---------------------- OPTIONAL: SAVE TO CSV. RUN ON LOCAL ----------------------
# filtered_routes_df.to_csv("filtered_routes.csv", index=False)
# filtered_trips_df.to_csv("filtered_trips.csv", index=False)
# filtered_stop_times_df.to_csv("filtered_stop_times.csv", index=False)
# filtered_stops_df.to_csv("filtered_stops.csv", index=False)
