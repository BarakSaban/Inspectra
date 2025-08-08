from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import json
import math
from datetime import datetime, timedelta
import Actions
from Classes import Inspector

app = Flask(__name__, static_folder='static', template_folder='templates')

# ---------- Helpers ----------
def haversine_meters(lat1, lon1, lat2, lon2):
    # returns distance in meters
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    return 2 * R * math.asin(math.sqrt(a))

def parse_time_to_minutes(t_str):
    # Handles GTFS times like "25:10:00" (allowed)
    parts = t_str.split(':')
    if len(parts) < 2:
        raise ValueError("Bad time format")
    h = int(parts[0]); m = int(parts[1]); s = int(parts[2]) if len(parts) > 2 else 0
    return h*60 + m + s/60.0

# ---------- Load data once ----------
print("Loading GTFS filtered files...")
stops_gj = json.load(open('static/stops.geojson', 'r', encoding='utf-8'))
shapes_gj = json.load(open('static/shapes.geojson', 'r', encoding='utf-8'))
stop_shape_map = json.load(open('static/stop_shape_map.json', 'r', encoding='utf-8'))

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
    radius = float(data.get('radius', 5000))

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
        "stop": best,
        "distance_m": best_d,
        "mappings": mappings
    })


@app.route('/api/find_best_trip', methods=['POST'])
def api_find_best_trip():
    req = request.get_json()
    lat = float(req['lat']); lon = float(req['lon'])
    buffer_minutes = float(req.get('buffer', 3))
    radius_m = float(req.get('radius', 2000000000000)) #Should be 2000

    inspector = Inspector(inspector_id='local', name='Local', latitude=lat, longitude=lon, available=True)

    best = Actions.find_best_fine_trip(inspector,
                                       stops_df=stops_df,
                                       stop_times_df=stop_times_df,
                                       trips_df=trips_df,
                                       buffer_minutes=buffer_minutes,
                                       radius_m=radius_m
    )

    # For robustness, fallback - compute nearest stop + mapping
    # (if your find_best_fine_trip returns None)
    if not best:
        # fallback: nearest stop
        nearest_resp = nearest_stop_internal(lat, lon)
        return jsonify({"fallback": nearest_resp})

    # Find stop geometry and shape geometry for the selected option
    stop_id = str(best['stop_id'])
    mapping_entries = [m for m in stop_shape_map if str(m['stop_id']) == stop_id]
    chosen_map = mapping_entries[0] if mapping_entries else None
    shape_feature = None
    if chosen_map:
        shape_id = str(chosen_map.get('shape_id'))
        shape_feature = shape_lookup.get(shape_id)

    return jsonify({
        "best_option": best,
        "stop_feature": stop_lookup.get(stop_id),
        "shape_feature": shape_feature
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
