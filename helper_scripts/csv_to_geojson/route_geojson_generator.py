import pandas as pd
import json

# Load your filtered files
stop_times_df = pd.read_csv('filtered_stop_times.csv')
stops_df = pd.read_csv('filtered_stops.csv')
trips_df = pd.read_csv('filtered_trips.csv')

# Merge stop_times with stops to get lat/lon
merged = stop_times_df.merge(
    stops_df[['stop_id', 'stop_lat', 'stop_lon']],
    on='stop_id',
    how='left'
)

# Merge trips to get route_id
merged = merged.merge(
    trips_df[['trip_id', 'route_id']],
    on='trip_id',
    how='left'
)

features = []

# Group by trip_id to get each trip’s stop sequence
for trip_id, group in merged.groupby('trip_id'):
    group = group.sort_values('stop_sequence')

    # Build LineString of coordinates
    coordinates = [[row['stop_lon'], row['stop_lat']] for _, row in group.iterrows()]

    if len(coordinates) < 2:
        continue  # skip incomplete trips

    feature = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates
        },
        "properties": {
            "trip_id": int(trip_id),
            "route_id": int(group['route_id'].iloc[0])
        }
    }

    features.append(feature)

geojson = {
    "type": "FeatureCollection",
    "features": features
}

# Save it
with open('static/routes.geojson', 'w', encoding='utf-8') as f:
    json.dump(geojson, f, ensure_ascii=False, indent=2)

print("GeoJSON saved to static/routes.geojson")
