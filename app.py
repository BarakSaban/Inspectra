from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import json
import math
from datetime import datetime
from Actions import Actions
from Classes import Inspector
from unittest.mock import patch
import numpy as np
import sklearn
print(f"Version of sklearn is {sklearn.__version__}. sklearn is critical for osmnx to work.")

app = Flask(__name__, static_folder='static', template_folder='templates')

# Note: In production, ensure local location is actually accessed in find_best_trip and uncomment hardcoded location

stops_df = pd.read_csv("./gtfs/gtfs_filtered/stops.txt")
stop_times_df = pd.read_csv("./gtfs/gtfs_filtered/stop_times.txt")
trips_df = pd.read_csv("./gtfs/gtfs_filtered/trips.txt")
routes_df = pd.read_csv("./static/routes_with_avgs.csv") #TODO standardize as .txt

# Create the Actions instance
actions = Actions(stops_df, stop_times_df, trips_df, routes_df)

# ---------- Helpers ----------
def haversine_meters(lat1, lon1, lat2, lon2):
    # returns distance in meters
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    return 2 * R * math.asin(math.sqrt(a))

def to_serializable(obj):
    """Recursively convert pandas/numpy objects into JSON-safe Python types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, (pd.Series, pd.DataFrame)):
        return obj.to_dict(orient="records")
    elif isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_serializable(v) for v in obj]
    else:
        return obj

# ---------- Load data once ----------
print("Loading GTFS filtered files...")
stops_gj = json.load(open('static/stops.geojson', 'r', encoding='utf-8'))
stop_shape_map = json.load(open('static/stop_shape_map.json', 'r', encoding='utf-8'))
shapes_gj = json.load(open('static/shapes.geojson', 'r', encoding='utf-8'))

# Build quick lookup: stop_id -> stop feature
stop_lookup = {str(f['properties']['stop_id']): f for f in stops_gj.get('features', [])}

# Build shape lookup
shape_lookup = {str(f['properties'].get('shape_id')): f for f in shapes_gj.get('features', [])}

# Load stop_times & trips for Actions and calculations
stop_times_df = pd.read_csv('gtfs/gtfs_filtered/stop_times.txt', sep=',', encoding='utf-8')
trips_df = pd.read_csv('gtfs/gtfs_filtered/trips.txt', sep=',', encoding='utf-8')
routes_df = pd.read_csv('gtfs/gtfs_filtered/routes.txt', sep=',', encoding='utf-8')
stops_df = pd.read_csv('gtfs/gtfs_filtered/stops.txt', sep=',', encoding='utf-8')

# ---------- API endpoints ----------

@app.route('/api/nearest_stop', methods=['POST'])
def nearest_stop():
    data = request.get_json()
    lat = float(data['lat']); lon = float(data['lon'])

    # Find nearest stop (haversine)
    best = None; best_d = float('inf')
    for f in stops_gj.get('features', []):
        coords = f['geometry']['coordinates']  # [lon, lat]
        d = haversine_meters(lat, lon, coords[1], coords[0])
        if d < best_d:
            best_d = d; best = f

    if best is None:
        return jsonify({"error": "no stops"}), 404

    # find mapping entries
    stop_id = str(best['properties']['stop_id'])
    mappings = [m for m in stop_shape_map if str(m['stop_id']) == stop_id]

    return jsonify({
        "stop": to_serializable(best),
        "distance_m": to_serializable(best_d),
        "mappings": to_serializable(mappings)
    })


@app.route('/api/find_best_trip', methods=['POST'])
def api_find_best_trip():
    req = request.get_json()
    lat = 32.0880 #float(req['lat']) 
    lon = 34.7898 #float(req['lon'])
    buffer_minutes = float(req.get('buffer', 3))  # Should be 3
    radius_m = float(req.get('radius', 666))     # Should be 2000

    inspector = Inspector(inspector_id='local', name='Local', latitude=lat, longitude=lon, available=True)

    best = actions.find_best_fine_trip(
        inspector,
        buffer_minutes=buffer_minutes,
        radius_m=radius_m
    )

    if not best:
        nearest_resp = nearest_stop_internal(lat, lon)
        return jsonify({"fallback": nearest_resp})

    stop_id = str(best['stop_id'])
    trip_id = str(best['trip_id'])

    # Get stop geo
    stop_feature = stop_lookup.get(stop_id)

    # Get shape_id for this trip
    shape_id = None
    try:
        shape_id = str(trips_df.loc[trips_df['trip_id'] == trip_id, 'shape_id'].values[0])
        shape_id = shape_id.replace(".0", "")  # Sanitization, since trips_id has .0 after corresponding shape_id unlike all other dfs
    except Exception:
        shape_id = None

    shape_feature = shape_lookup.get(shape_id) if shape_id else None

    print(f"Selected stop_id: {stop_id}")
    print(f"Selected trip_id: {trip_id}")
    print(f"Matched shape_id: {shape_id}")
    print(f"Shape found: {'Yes' if shape_feature else 'No'}")

    return jsonify({
        "best_option": to_serializable(best),
        "stop_feature": to_serializable(stop_feature),
        "shape_feature": to_serializable(shape_feature)
    })

# helper internal nearest used above
def nearest_stop_internal(lat, lon):
    best = None; best_d = float('inf')
    for f in stops_gj.get('features', []):
        coords = f['geometry']['coordinates']  # [lon, lat]
        d = haversine_meters(lat, lon, coords[1], coords[0])
        if d < best_d:
            best_d = d; best = f
    return {"stop": best, "distance_m": best_d, "mappings": [m for m in stop_shape_map if str(m['stop_id']) == str(best['properties']['stop_id'])]}

# static frontend
@app.route('/')
def index():
    return send_from_directory('templates', 'map.html')

if __name__ == '__main__':
    app.run(debug=True)
