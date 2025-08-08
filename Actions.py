import math
from datetime import datetime, timedelta
import pandas as pd

# --------------------------
# [1] Haversine distance between two (lat, lon) pairs -> meters
# --------------------------
def haversine_meters(pos1, pos2):
    """
    pos1, pos2: (lat, lon)
    returns distance in meters
    """
    lat1, lon1 = float(pos1[0]), float(pos1[1])
    lat2, lon2 = float(pos2[0]), float(pos2[1])
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*(math.sin(dlambda/2.0)**2)
    return 2 * R * math.asin(math.sqrt(a))

# --------------------------
# [2] Walking time in minutes given distance in meters
# --------------------------
def time_to_walk(distance_m):
    """
    walking_speed_m_per_min approx 83.33 m/min (5 km/h)
    """
    walking_speed = 5000 / 60.0  # 83.333... m/min
    return distance_m / walking_speed

# --------------------------
# [3] Parse GTFS time string (handles >24:00:00) -> minutes since midnight (float)
# --------------------------
def parse_gtfs_time_to_minutes(t_str):
    """
    Parse HH:MM:SS where HH may be >= 24 (GTFS allows >24 for next-day times).
    Returns minutes from midnight (float).
    """
    if not isinstance(t_str, str):
        raise ValueError("Time must be a string in HH:MM:SS format")
    parts = t_str.split(":")
    if len(parts) < 2:
        raise ValueError("Time format invalid")
    h = int(parts[0])
    m = int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return h * 60 + m + s / 60.0

# --------------------------
# [4] Minutes until arrival from now (can be negative if past)
# --------------------------
def minutes_until_arrival(arrival_time_str, now_time=None):
    """
    Returns minutes from 'now' until arrival_time_str.
    arrival_time_str can be GTFS style (e.g., "25:10:00").
    """
    if now_time is None:
        now_time = datetime.now()

    # compute now as minutes since midnight, but we must allow comparing to times >24h
    now_minutes = now_time.hour * 60 + now_time.minute + now_time.second / 60.0

    try:
        arrival_minutes = parse_gtfs_time_to_minutes(arrival_time_str)
    except Exception:
        # if parsing fails, return a big negative number to skip it
        return -99999

    # If arrival_minutes is less than now_minutes but arrival_hours >=24,
    # arrival_minutes may be e.g. 1500 which is > now_minutes. So just subtract.
    return arrival_minutes - now_minutes

# --------------------------
# [5] Get all nearby stations within radius (meters)
# --------------------------
def get_nearby_stations(inspector_pos, stops_df, radius_m=2000):
    """
    inspector_pos: (lat, lon)
    stops_df: pandas DataFrame with 'stop_id', 'stop_lat', 'stop_lon' columns
    returns list of tuples (stop_id, distance_m) sorted by distance
    """
    nearby = []
    # Ensure stops_df has expected columns
    if 'stop_lat' not in stops_df.columns or 'stop_lon' not in stops_df.columns:
        raise KeyError("stops_df must have 'stop_lat' and 'stop_lon' columns")

    for _, stop in stops_df.iterrows():
        stop_pos = (float(stop['stop_lat']), float(stop['stop_lon']))
        dist = haversine_meters(inspector_pos, stop_pos)
        if dist <= radius_m:
            nearby.append((str(stop['stop_id']), dist))
    return sorted(nearby, key=lambda x: x[1])  # sorted by closest

# --------------------------
# [6] Get reachable trips for inspector (must arrive buffer_minutes early)
# --------------------------
def get_reachable_trips(inspector, stops_df, stop_times_df, buffer_minutes=3, radius_m=2000):
    """
    Returns list of trips the inspector can realistically reach in time.
    inspector: object with .lat and .lon (or Inspector)
    stops_df: pandas DataFrame (with stop_id, stop_lat, stop_lon)
    stop_times_df: pandas DataFrame (with trip_id, stop_id, arrival_time)
    """
    inspector_pos = (float(getattr(inspector, 'lat', inspector.latitude)),
                     float(getattr(inspector, 'lon', inspector.longitude)))

    nearby_stations = get_nearby_stations(inspector_pos, stops_df, radius_m=radius_m)

    reachable = []

    for stop_id, distance_m in nearby_stations:
        walk_minutes = time_to_walk(distance_m)

        stop_times = stop_times_df[stop_times_df['stop_id'].astype(str) == str(stop_id)]
        for _, row in stop_times.iterrows():
            arrival_time_str = row.get('arrival_time') or row.get('arrival_time', '')
            minutes_to_arrival = minutes_until_arrival(str(arrival_time_str))
            if walk_minutes + buffer_minutes <= minutes_to_arrival:
                reachable.append({
                    'trip_id': row['trip_id'],
                    'stop_id': stop_id,
                    'arrival_time': arrival_time_str,
                    'walk_time': round(walk_minutes, 1),
                    'distance_m': int(distance_m),
                    'minutes_until_arrival': round(minutes_to_arrival, 1)
                })

    return reachable

# --------------------------
# [7] find_optional_lines -> returns DataFrame of options inspector can reach
# --------------------------
def find_optional_lines(inspector_lat, inspector_lon, stops_df, stop_times_df, buffer_minutes=3, radius_m=2000):
    """
    For a given inspector's coordinates, find all reachable bus trips.
    Returns a pandas DataFrame (sorted) with reachable trip options.
    """
    inspector_pos = (float(inspector_lat), float(inspector_lon))

    # Step 1: Find nearby stations
    nearby_stations = get_nearby_stations(inspector_pos, stops_df, radius_m=radius_m)

    reachable = []

    for stop_id, distance_m in nearby_stations:
        walk_minutes = time_to_walk(distance_m)
        stop_times = stop_times_df[stop_times_df['stop_id'].astype(str) == str(stop_id)]

        for _, row in stop_times.iterrows():
            arrival_time_str = row.get('arrival_time') or row.get('arrival_time', '')
            minutes_to_arrival = minutes_until_arrival(str(arrival_time_str))
            if walk_minutes + buffer_minutes <= minutes_to_arrival:
                reachable.append({
                    'trip_id': row['trip_id'],
                    'stop_id': stop_id,
                    'arrival_time': arrival_time_str,
                    'walk_time': round(walk_minutes, 1),
                    'distance_m': int(distance_m),
                    'minutes_until_arrival': round(minutes_to_arrival, 1)
                })

    if not reachable:
        return pd.DataFrame([], columns=['trip_id', 'stop_id', 'arrival_time', 'walk_time', 'distance_m', 'minutes_until_arrival'])

    return pd.DataFrame(reachable).sort_values(by='minutes_until_arrival')

# --------------------------
# [8] find_best_fine_trip -> main decision function
# --------------------------
def find_best_fine_trip(inspector, stops_df, stop_times_df, trips_df, buffer_minutes=3, radius_m=2000):
    """
    Returns the best reachable trip (with most possible fines) for the inspector.
    inspector: object with .lat / .lon and .available attribute
    stops_df, stop_times_df, trips_df: pandas DataFrames
    """
    if not getattr(inspector, 'available', True):
        return None

    # now in minutes
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute + now.second / 60.0

    # get reachable candidates
    reachable_df = find_optional_lines(inspector.lat, inspector.lon, stops_df, stop_times_df, buffer_minutes, radius_m)
    if reachable_df.empty:
        return None

    best_option = None
    max_fines = -1

    checked_trips = set()

    for _, row in reachable_df.iterrows():
        trip_id = row['trip_id']
        stop_id = row['stop_id']
        minutes_until_arrival = float(row['minutes_until_arrival'])

        if trip_id in checked_trips:
            continue
        checked_trips.add(trip_id)

        trip_stop_times = stop_times_df[stop_times_df['trip_id'] == trip_id]
        if trip_stop_times.empty:
            continue

        # compute latest arrival minute for this trip (handle GTFS >24h)
        arrival_minutes_list = []
        for t in trip_stop_times['arrival_time']:
            try:
                arrival_minutes_list.append(parse_gtfs_time_to_minutes(str(t)))
            except Exception:
                continue
        if not arrival_minutes_list:
            continue
        latest_arrival_minutes = max(arrival_minutes_list)

        time_on_board = latest_arrival_minutes - now_minutes
        if time_on_board <= 0:
            continue

        fines_possible = int(time_on_board // 5)

        # trips_df may contain an 'AvgDontPay' or similar column; handle missing gracefully
        avg_dont_pay = 0
        if 'AvgDontPay' in trips_df.columns:
            try:
                val = trips_df.loc[trips_df['trip_id'] == trip_id, 'AvgDontPay']
                if not val.empty:
                    avg_dont_pay = float(val.values[0])
            except Exception:
                avg_dont_pay = 0

        potential_fines = min(fines_possible, int(avg_dont_pay) if avg_dont_pay else fines_possible)

        if potential_fines > max_fines:
            max_fines = potential_fines
            best_option = {
                'trip_id': trip_id,
                'stop_id': stop_id,
                'arrival_time': row['arrival_time'],
                'walk_time_min': row['walk_time'],
                'distance_m': row['distance_m'],
                'minutes_until_arrival': minutes_until_arrival,
                'time_on_board_min': round(time_on_board, 1),
                'AvgDontPay': avg_dont_pay,
                'potential_fines': int(potential_fines)
            }

    return best_option
