from flask import Flask, render_template, jsonify, request, redirect
import pandas as pd
import json
import math
from Classes import Inspector
from Actions import Actions
import numpy as np
import sklearn

print(f"Version of sklearn is {sklearn.__version__}. sklearn is critical for osmnx to work.")

app = Flask(__name__, static_folder='static', template_folder='templates')

# ---------- Load CSV and JSON data ----------
stops_df = pd.read_csv("./gtfs/gtfs_filtered/stops.txt")
stop_times_df = pd.read_csv("./gtfs/gtfs_filtered/stop_times.txt")
trips_df = pd.read_csv("./gtfs/gtfs_filtered/trips.txt")
routes_df = pd.read_csv("./static/routes_with_avgs.csv")

actions = Actions(stops_df, stop_times_df, trips_df, routes_df)

stops_gj = json.load(open('static/stops.geojson', 'r', encoding='utf-8'))
stop_shape_map = json.load(open('static/stop_shape_map.json', 'r', encoding='utf-8'))
shapes_gj = json.load(open('static/shapes.geojson', 'r', encoding='utf-8'))

stop_lookup = {str(f['properties']['stop_id']): f for f in stops_gj.get('features', [])}
shape_lookup = {str(f['properties'].get('shape_id')): f for f in shapes_gj.get('features', [])}

# ---------- Helper functions ----------
def haversine_meters(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    return 2 * R * math.asin(math.sqrt(a))

def to_serializable(obj):
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

# ---------- Routes ----------
@app.route('/')
def root():
    return redirect('/admin')

@app.route('/admin')
def admin_dashboard():
    return render_template('Admin_main_dashboard.html')

@app.route('/analytics')
def analytics_page():
    return render_template('Analytics.html')

@app.route('/api/nearest_stop', methods=['POST'])
def nearest_stop():
    data = request.get_json()
    lat = float(data['lat'])
    lon = float(data['lon'])
    best = None
    best_d = float('inf')
    for f in stops_gj.get('features', []):
        coords = f['geometry']['coordinates']
        d = haversine_meters(lat, lon, coords[1], coords[0])
        if d < best_d:
            best_d = d
            best = f
    if best is None:
        return jsonify({"error": "no stops"}), 404
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
    lat = float(req.get('lat', 32.0880))
    lon = float(req.get('lon', 34.7898))
    buffer_minutes = float(req.get('buffer', 3))
    radius_m = float(req.get('radius', 666))
    inspector = Inspector(inspector_id='local', name='Local', latitude=lat, longitude=lon, available=True)
    best = actions.find_best_fine_trip(inspector, buffer_minutes=buffer_minutes, radius_m=radius_m)
    if not best:
        return jsonify({"fallback": "No suitable trip found"})
    stop_id = str(best['stop_id'])
    trip_id = str(best['trip_id'])
    stop_feature = stop_lookup.get(stop_id)
    shape_id = None
    try:
        shape_id = str(trips_df.loc[trips_df['trip_id'] == trip_id, 'shape_id'].values[0]).replace(".0", "")
    except:
        shape_id = None
    shape_feature = shape_lookup.get(shape_id) if shape_id else None
    return jsonify({
        "best_option": to_serializable(best),
        "stop_feature": to_serializable(stop_feature),
        "shape_feature": to_serializable(shape_feature)
    })

@app.route('/api/analytics')
def api_analytics():
    data = {
        "totalFines": 1432,
        "avgEfficiency": 82,
        "completedAssignments": 10,
        "inspectors": [
            {"name": "John Doe", "totalFines": 1200},
            {"name": "Jane Smith", "totalFines": 400},
            {"name": "Lior Ben", "totalFines": 300},
            {"name": "Dana Levi", "totalFines": 150}
        ],
        "hourly": [
            {"hour": "07:00", "fines": 250},
            {"hour": "09:00", "fines": 800},
            {"hour": "15:00", "fines": 900},
            {"hour": "19:00", "fines": 850}
        ],
        "assignmentStatus": [
            {"name": "Completed", "value": 30},
            {"name": "Pending", "value": 50},
            {"name": "Inspecting", "value": 10}
        ]
    }
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True)
