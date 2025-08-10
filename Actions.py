import osmnx as ox
import networkx as nx
from shapely.geometry import LineString
import pandas as pd
from datetime import datetime

# Note: In production, delete fake_now and uncomment every "datetime.now" instance
fake_now = datetime(2025, 8, 9, 7, 30, 15)
class Actions:
    def __init__(self, stops_df, stop_times_df, trips_df):
        self.stops_df = stops_df
        self.stop_times_df = stop_times_df
        self.trips_df = trips_df

    # --------------------------
    # Build walking network (cached per search)
    # --------------------------
    def build_walking_graph(self, center_lat, center_lon, radius_m=2000):
        print("Building walking graph at:", center_lat, center_lon, "radius:", radius_m)
        G = ox.graph_from_point((center_lat, center_lon), dist=radius_m, network_type='walk')
        nx.set_edge_attributes(G, values=5, name='speed_kph')  # walking speed ~5 km/h
        G = ox.add_edge_travel_times(G)  # adds 'travel_time' in seconds
        return G

    # --------------------------
    # Get walking time and geometry between two points
    # --------------------------
    def get_walking_time_and_route(self, G, origin, destination):
        orig_node = ox.distance.nearest_nodes(G, origin[1], origin[0])  # (lon, lat)
        dest_node = ox.distance.nearest_nodes(G, destination[1], destination[0])

        # Shortest path by travel time
        path_nodes = nx.shortest_path(G, orig_node, dest_node, weight='travel_time')
        travel_time_sec = nx.shortest_path_length(G, orig_node, dest_node, weight='travel_time')

        # Build geometry
        path_coords = []
        for u, v in zip(path_nodes[:-1], path_nodes[1:]):
            edge_data = min(G.get_edge_data(u, v).values(), key=lambda x: x.get('length', 0))
            if 'geometry' in edge_data:
                path_coords.extend(list(edge_data['geometry'].coords))
            else:
                path_coords.append((G.nodes[u]['x'], G.nodes[u]['y']))
                path_coords.append((G.nodes[v]['x'], G.nodes[v]['y']))

        route_line = LineString(path_coords)
        walk_minutes = round(travel_time_sec / 60, 2)
        return walk_minutes, route_line

    # --------------------------
    # Find nearby stations with realistic walking paths
    # --------------------------
    def get_nearby_stations_osm(self, inspector_pos, radius_m=2000, max_walk_minutes=8):
        G = self.build_walking_graph(inspector_pos[0], inspector_pos[1], radius_m)
        nearby = []

        for _, stop in self.stops_df.iterrows():
            stop_pos = (stop['stop_lat'], stop['stop_lon'])
            try:
                walk_minutes, route_geom = self.get_walking_time_and_route(G, inspector_pos, stop_pos)
                if walk_minutes <= max_walk_minutes:
                    nearby.append((stop['stop_id'], walk_minutes, route_geom))
            except Exception as e:
                print(f"Error finding route to stop {stop['stop_id']}: {e}")
                continue
        print(f"Nearby stations array (called from get_nearby_stations_osm):\n{nearby}")
        return sorted(nearby, key=lambda x: x[1])

    # --------------------------
    # Convert arrival time to minutes from now
    # --------------------------
    def minutes_until_arrival(self, arrival_time_str, now_time=None):
        if now_time is None:
            now_time = fake_now #datetime.now()
        now_minutes = now_time.hour * 60 + now_time.minute + now_time.second / 60

        h, m, s = map(int, arrival_time_str.split(":"))
        arrival_minutes = h * 60 + m + s / 60
        return arrival_minutes - now_minutes

    # --------------------------
    # Find all reachable trips with realistic walking
    # --------------------------
    def find_optional_lines(self, inspector_lat, inspector_lon, buffer_minutes=3, radius_m=2000):
        inspector_pos = (inspector_lat, inspector_lon)
        nearby_stations = self.get_nearby_stations_osm(inspector_pos, radius_m=radius_m)
        print(f"Currently running find_optional_lines with pos {inspector_pos} on stations:\n{nearby_stations}")
        reachable = []
        for stop_id, walk_minutes, route_geom in nearby_stations:
            stop_times = self.stop_times_df[self.stop_times_df['stop_id'] == stop_id]
            for _, row in stop_times.iterrows():
                minutes_to_arrival = self.minutes_until_arrival(row['arrival_time'])
                if walk_minutes + buffer_minutes <= minutes_to_arrival:
                    reachable.append({
                        'trip_id': row['trip_id'],
                        'stop_id': stop_id,
                        'arrival_time': row['arrival_time'],
                        'walk_time': walk_minutes,
                        'route_geometry': route_geom,  # store walking path
                        'minutes_until_arrival': round(minutes_to_arrival, 1)
                    })
        print(f"Reachable array (called from find_optional_lines):\n{reachable}")
        if not reachable:
            return pd.DataFrame()
        
        return pd.DataFrame(reachable).sort_values(by='minutes_until_arrival')

    # --------------------------
    # Find best trip for fines potential
    # --------------------------
    def find_best_fine_trip(self, inspector, buffer_minutes=3, radius_m=2000):
        if not inspector.available:
            print("Inspector unavailable, exiting...")
            return None

        now = fake_now #datetime.now()
        now_minutes = now.hour * 60 + now.minute + now.second / 60

        reachable_df = self.find_optional_lines(inspector.lat, inspector.lon, buffer_minutes, radius_m)
        if reachable_df.empty:
            print("Reachable lines empty, existing...")
            return None

        best_option = None
        max_fines = 0
        checked_trips = set()

        for _, row in reachable_df.iterrows():
            trip_id = row['trip_id']
            if trip_id in checked_trips:
                continue
            checked_trips.add(trip_id)

            trip_stop_times = self.stop_times_df[self.stop_times_df['trip_id'] == trip_id]
            if trip_stop_times.empty:
                continue

            try:
                latest_arrival_minutes = max([
                    int(t.split(":")[0]) * 60 + int(t.split(":")[1]) + int(t.split(":")[2]) / 60
                    for t in trip_stop_times['arrival_time']
                    if isinstance(t, str) and len(t.split(":")) == 3
                ])
            except:
                continue

            time_on_board = latest_arrival_minutes - now_minutes
            if time_on_board <= 0:
                continue

            fines_possible = int(time_on_board // 5)

            avg_dont_pay = self.trips_df[self.trips_df['trip_id'] == trip_id].get('AvgDontPay')
            avg_dont_pay = float(avg_dont_pay.values[0]) if not avg_dont_pay.empty else 0

            potential_fines = min(fines_possible, int(avg_dont_pay))

            if potential_fines > max_fines:
                max_fines = potential_fines
                best_option = {
                    'trip_id': trip_id,
                    'stop_id': row['stop_id'],
                    'arrival_time': row['arrival_time'],
                    'walk_time': row['walk_time'],
                    'route_geometry': row['route_geometry'],  # walking path to station
                    'minutes_until_arrival': row['minutes_until_arrival'],
                    'time_on_board_min': round(time_on_board, 1),
                    'AvgDontPay': avg_dont_pay,
                    'potential_fines': potential_fines
                }
        print(f"Best option array (called from find_best_fine_trip):\n{best_option}")
        return best_option