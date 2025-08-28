import pandas as pd
import json

# Load filtered GTFS TXT files (with ID columns as strings)
stop_times_df = pd.read_csv("./gtfs/gtfs_filtered/stop_times.txt", sep=",", encoding="utf-8", dtype={"stop_id": str, "trip_id": str})
trips_df = pd.read_csv("./gtfs/gtfs_filtered/trips.txt", sep=",", encoding="utf-8", dtype={"trip_id": str, "route_id": str, "shape_id": str})
routes_df = pd.read_csv("./gtfs/gtfs_filtered/routes.txt", sep=",", encoding="utf-8", dtype={"route_id": str})

# Merge stop_times with trips to get route_id and shape_id
merged = stop_times_df.merge(
    trips_df[['trip_id', 'route_id', 'shape_id']],
    on='trip_id',
    how='left'
)

# Add route metadata (optional but nice for map popups)
merged = merged.merge(
    routes_df[['route_id', 'route_short_name', 'route_long_name']],
    on='route_id',
    how='left'
)

# Clean up possible float-looking shape_ids like "1234.0"
merged['shape_id'] = merged['shape_id'].astype(str).str.replace(r'\.0$', '', regex=True)

# Select only needed columns & drop duplicates
map_df = merged[['stop_id', 'trip_id', 'route_id', 'shape_id',
                 'route_short_name', 'route_long_name']].drop_duplicates()

# Convert to list of dicts for JSON
records = map_df.to_dict(orient="records")

# Save as JSON
with open("stop_shape_map.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(f"Saved {len(records)} records to stop_shape_map.json")
