import os
import zipfile
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
import shutil

# --- CONFIG ---
# 1) Path to your GTFS zip file
gtfs_zip_path = r"./gtfs/israel-public-transportation.zip"

# 2) Temporary extraction directory
extract_dir = "./gtfs/gtfs_extracted/"

# 3) Path to output filtered files
OUTPUT_PATH = "./gtfs/gtfs_filtered/"

# 4) target route_ids (lines, can be found in routes.txt in gtfs)
MY_ROUTE_IDS = [ 
    "39165", "39166", #Adding in pairs, one for the way forward and other ofr backwards
    "27901", "27902",
    "27081", "27082",
    "27083", "27084",
    "34619", "34620"
]

# --- Prepare folders ---
os.makedirs(extract_dir, exist_ok=True)
os.makedirs(OUTPUT_PATH, exist_ok=True)

# --- Extract necessary GTFS files ---
gtfs_files = [
    'routes.txt',
    'trips.txt',
    'stop_times.txt',
    'stops.txt',
    'shapes.txt',
    'calendar.txt',
    'calendar_dates.txt',
    'agency.txt'
]

print(f"🔍 Extracting GTFS files from: {gtfs_zip_path}")
with zipfile.ZipFile(gtfs_zip_path, 'r') as z:
    for file in gtfs_files:
        if file in z.namelist():
            z.extract(file, path=extract_dir)
            print(f"✅ Extracted: {file}")
        else:
            print(f"⚠️ Warning: {file} not found in GTFS zip!")

# --- 1) Filter routes ---
routes = pd.read_csv(extract_dir + "routes.txt", dtype={'route_id': str})
routes['route_id'] = routes['route_id'].str.strip()
filtered_routes = routes[routes['route_id'].isin(MY_ROUTE_IDS)]
filtered_routes.to_csv(OUTPUT_PATH + "routes.txt", index=False)
print(f"✅ routes.txt: {len(filtered_routes)} routes kept")

# --- 2) Filter trips ---
trips = pd.read_csv(extract_dir + "trips.txt", dtype={'route_id': str})
trips['route_id'] = trips['route_id'].str.strip()
filtered_trips = trips[trips['route_id'].isin(filtered_routes['route_id'])]
filtered_trips.to_csv(OUTPUT_PATH + "trips.txt", index=False)
print(f"✅ trips.txt: {len(filtered_trips)} trips kept")

# --- 3) Filter stop_times ---
stop_times = pd.read_csv(extract_dir + "stop_times.txt")
filtered_stop_times = stop_times[stop_times['trip_id'].isin(filtered_trips['trip_id'])]
filtered_stop_times.to_csv(OUTPUT_PATH + "stop_times.txt", index=False)
print(f"✅ stop_times.txt: {len(filtered_stop_times)} stop times kept")

# --- 4) Filter stops ---
stops = pd.read_csv(extract_dir + "stops.txt")
used_stop_ids = filtered_stop_times['stop_id'].unique()
filtered_stops = stops[stops['stop_id'].isin(used_stop_ids)]
filtered_stops.to_csv(OUTPUT_PATH + "stops.txt", index=False)
print(f"✅ stops.txt: {len(filtered_stops)} stops kept")

# --- 5) Filter shapes ---
try:
    shapes = pd.read_csv(extract_dir + "shapes.txt")
    used_shape_ids = filtered_trips['shape_id'].dropna().unique()
    filtered_shapes = shapes[shapes['shape_id'].isin(used_shape_ids)]
    filtered_shapes.to_csv(OUTPUT_PATH + "shapes.txt", index=False)
    print(f"✅ shapes.txt: {len(filtered_shapes)} shape points kept")
except FileNotFoundError:
    print("⚠️ shapes.txt not found — skipping")

# # --- 6) Filter calendar ---
# try:
#     calendar = pd.read_csv(extract_dir + "calendar.txt")
#     service_ids = filtered_trips['service_id'].unique()
#     filtered_calendar = calendar[calendar['service_id'].isin(service_ids)]
#     filtered_calendar.to_csv(OUTPUT_PATH + "calendar.txt", index=False)
#     print(f"✅ calendar.txt: {len(filtered_calendar)} services kept")
# except FileNotFoundError:
#     print("⚠️ calendar.txt not found — skipping")

# # --- 7) Filter calendar_dates ---
# try:
#     calendar_dates = pd.read_csv(extract_dir + "calendar_dates.txt")
#     filtered_calendar_dates = calendar_dates[calendar_dates['service_id'].isin(service_ids)]
#     filtered_calendar_dates.to_csv(OUTPUT_PATH + "calendar_dates.txt", index=False)
#     print(f"✅ calendar_dates.txt: {len(filtered_calendar_dates)} exceptions kept")
# except FileNotFoundError:
#     print("⚠️ calendar_dates.txt not found — skipping")

try:
    shutil.rmtree(extract_dir)
    print(f"🧹 Deleted temporary folder: {extract_dir}")
except Exception as e:
    print(f"⚠️ Could not delete {extract_dir}: {e}")

print("\n🎉 All done! Your filtered GTFS is in:", OUTPUT_PATH)



# --- Convert stops to GeoJSON ---
print("🌍 Generating stops.geojson...")
stops_gdf = gpd.GeoDataFrame(
    filtered_stops,
    geometry=gpd.points_from_xy(filtered_stops['stop_lon'], filtered_stops['stop_lat']),
    crs="EPSG:4326"
)
stops_gdf.to_file(OUTPUT_PATH + "stops.geojson", driver="GeoJSON")
print(f"✅ Created {OUTPUT_PATH}stops.geojson")

# --- Convert shapes to GeoJSON ---
try:
    if not filtered_shapes.empty:
        print("🌍 Generating shapes.geojson...")
        # Sort shape points properly
        shapes_sorted = filtered_shapes.sort_values(by=['shape_id', 'shape_pt_sequence'])

        lines = []
        for shape_id, group in shapes_sorted.groupby('shape_id'):
            line = LineString(zip(group['shape_pt_lon'], group['shape_pt_lat']))
            lines.append({'shape_id': shape_id, 'geometry': line})

        shapes_gdf = gpd.GeoDataFrame(lines, crs="EPSG:4326")
        shapes_gdf.to_file(OUTPUT_PATH + "shapes.geojson", driver="GeoJSON")
        print(f"✅ Created {OUTPUT_PATH}shapes.geojson")
    else:
        print("⚠️ No shapes found — skipping shapes.geojson.")
except Exception as e:
    print(f"⚠️ Could not generate shapes.geojson: {e}")