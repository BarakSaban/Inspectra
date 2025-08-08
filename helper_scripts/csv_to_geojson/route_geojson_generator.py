import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

# Load shapes.txt (from your filtered GTFS)
shapes_df = pd.read_csv('./gtfs/gtfs_filtered/shapes.txt')

# Sort by shape_id and sequence
shapes_df = shapes_df.sort_values(by=['shape_id', 'shape_pt_sequence'])

features = []
for shape_id, group in shapes_df.groupby('shape_id'):
    coordinates = list(zip(group['shape_pt_lon'], group['shape_pt_lat']))

    if len(coordinates) < 2:
        continue  # skip broken shapes

    line = LineString(coordinates)

    features.append({
        'type': 'Feature',
        'geometry': line,
        'properties': {'shape_id': shape_id}
    })

gdf = gpd.GeoDataFrame.from_features(features, crs='EPSG:4326')

# Save it
gdf.to_file('./static/shapes.geojson', driver='GeoJSON')

print("shapes.geojson created and saved.")
