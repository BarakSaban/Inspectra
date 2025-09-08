import os
import zipfile
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString
import shutil

# --- CONFIG ---
gtfs_zip_path = r"C:\Users\User\Documents\INSPECTRA\Data\tlv_busses_gtfs.zip"
extract_dir = "./gtfs/gtfs_extracted/"
OUTPUT_PATH = "./gtfs/gtfs_filtered/"

# Allowed cities pool
ALLOWED_CITIES = [
    "בני ברק", "רמת גן", "גבעתיים",
    "חולון", "בת ים", "רמת השרון",
    "הרצליה", "תל אביב"
]

def main():
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(OUTPUT_PATH, exist_ok=True)

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

    # --- 1) Filter routes: both endpoints must be in the ALLOWED_CITIES pool ---
    routes = pd.read_csv(extract_dir + "routes.txt", dtype={'route_id': str})

    def both_endpoints_in_pool(row):
        name = str(row.get('route_long_name', ''))
        if not name or pd.isna(name):
            name = str(row.get('route_desc', ''))
        if '<->' in name:
            origin, destination = name.split('<->', 1)
            if any(city in origin for city in ALLOWED_CITIES) and any(city in destination for city in ALLOWED_CITIES):
                return True
        return False

    filtered_routes = routes[routes.apply(both_endpoints_in_pool, axis=1)]
    filtered_routes.to_csv(OUTPUT_PATH + "routes.txt", index=False)
    print(f"✅ routes.txt: {len(filtered_routes)} routes kept (both endpoints in pool)")

    print("🔎 Example matching routes:")
    print(filtered_routes['route_long_name'].head(10).to_string(index=False))

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

    # --- 4) Filter stops: now keep all stops in allowed cities ---
    stops = pd.read_csv(extract_dir + "stops.txt")

    def stop_in_allowed_city(row):
        name = str(row.get('stop_name', ''))
        return any(city in name for city in ALLOWED_CITIES)

    filtered_stops = stops[stops.apply(stop_in_allowed_city, axis=1)]
    filtered_stops.to_csv(OUTPUT_PATH + "stops.txt", index=False)
    print(f"✅ stops.txt: {len(filtered_stops)} stops kept (all stops in allowed cities)")

    # --- 5) Filter shapes ---
    try:
        shapes = pd.read_csv(extract_dir + "shapes.txt")
        used_shape_ids = filtered_trips['shape_id'].dropna().unique()
        filtered_shapes = shapes[shapes['shape_id'].isin(used_shape_ids)]
        filtered_shapes.to_csv(OUTPUT_PATH + "shapes.txt", index=False)
        print(f"✅ shapes.txt: {len(filtered_shapes)} shape points kept")
    except FileNotFoundError:
        filtered_shapes = pd.DataFrame()
        print("⚠️ shapes.txt not found — skipping")

    # --- Cleanup extraction folder ---
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

if __name__ == "__main__":
    main()
