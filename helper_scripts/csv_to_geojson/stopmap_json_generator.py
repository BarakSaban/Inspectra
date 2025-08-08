import pandas as pd
import json

# Load filtered GTFS TXT files (as CSVs)
stop_times_df = pd.read_csv("stop_times.txt", sep=",", encoding="utf-8")
trips_df = pd.read_csv("trips.txt", sep=",", encoding="utf-8")
routes_df = pd.read_csv("routes.txt", sep=",", encoding="utf-8")

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

# Select only needed columns & drop duplicates
map_df = merged[['stop_id', 'trip_id', 'route_id', 'shape_id',
                 'route_short_name', 'route_long_name']].drop_duplicates()

# Convert to list of dicts for JSON
records = map_df.to_dict(orient="records")

# Save as JSON
with open("stop_shape_map.json", "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(f"✅ Saved {len(records)} records to stop_shape_map.json")
