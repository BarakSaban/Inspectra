import pandas as pd
import json

# Load your CSV
df = pd.read_csv('filtered_stops.csv')

# Build GeoJSON
features = []
for _, row in df.iterrows():
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [row['stop_lon'], row['stop_lat']]
        },
        "properties": {
            "stop_id": row['stop_id'],
            "stop_name": row['stop_name']
        }
    }
    features.append(feature)

geojson = {
    "type": "FeatureCollection",
    "features": features
}

with open('static/stops.geojson', 'w', encoding='utf-8') as f:
    json.dump(geojson, f, ensure_ascii=False, indent=2)

print("GeoJSON saved to static/stops.geojson")
