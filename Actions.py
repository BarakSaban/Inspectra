import osmnx as ox
import networkx as nx
from shapely.geometry import LineString
import pandas as pd
from datetime import datetime
from scipy.spatial import KDTree
import numpy as np
import math
from shapely.geometry import mapping


class Actions:
    def __init__(self, stops_df, stop_times_df, trips_df, routes_df):
        self.stops_df = stops_df.reset_index(drop=True)
        self.stop_times_df = stop_times_df
        self.trips_df = trips_df
        self.routes_df = routes_df

        # ---------- (1) KDTree in METERS (local projection) ----------
        # Build a local, near-conformal projection to meters using a fixed reference latitude.
        self._R = 6371000.0  # Earth radius in meters
        self._ref_lat_rad = math.radians(float(self.stops_df["stop_lat"].mean()))
        # Vectorized lat/lon -> (x,y) meters
        def to_xy(lat, lon):
            lat_rad = np.radians(lat)
            lon_rad = np.radians(lon)
            x = lon_rad * math.cos(self._ref_lat_rad) * self._R
            y = lat_rad * self._R
            return np.column_stack((x, y))

        self._stop_lat = self.stops_df["stop_lat"].to_numpy(dtype=float)
        self._stop_lon = self.stops_df["stop_lon"].to_numpy(dtype=float)
        self._stop_id  = self.stops_df["stop_id"].to_numpy()

        self._stop_xy = to_xy(self._stop_lat, self._stop_lon)    # shape (N,2) in meters
        self.kdtree = KDTree(self._stop_xy)                       # Euclidean (meters)

        # ---------- (5) Precompute stop_id -> stop_times DataFrame ----------
        # O(1) lookups instead of repeated DataFrame filtering.
        self.stop_times_map = {sid: df for sid, df in self.stop_times_df.groupby("stop_id")}

        # ---------- (6) Precompute trip_id -> AvgDontPay ----------
        if "AvgDontPay" in self.trips_df.columns:
            self.avg_dont_pay_map = dict(zip(self.trips_df["trip_id"], self.trips_df["AvgDontPay"]))
        else:
            self.avg_dont_pay_map = {}
            print("WARNING!!!: Avg Dont pay map is empty!")

        # Walking graph cache
        self._cached_graph = None
        self._cached_center = None  # (lat, lon)
        self._cached_radius = None  # meters

    # --------------------------
    # Utils
    # --------------------------
    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlbd = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlbd/2)**2
        return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _to_xy_single(self, lat, lon):
        # Same projection used for KDTree
        x = math.radians(lon) * math.cos(self._ref_lat_rad) * self._R
        y = math.radians(lat) * self._R
        return x, y

    def get_dontpay_value(self, route_id):
        now = datetime.now().time()
        hour = now.hour

        # Define the time ranges and corresponding columns
        time_slots = [
            ((6, 8), "DontPay - 06:00-08:59"),
            ((9, 11), "DontPay - 09:00-11:59"),
            ((12, 14), "DontPay - 12:00-14:59"),
            ((15, 17), "DontPay - 15:00-17:59"),
            ((18, 20), "DontPay - 18:00-20:59"),
            ((21, 23), "DontPay - 21:00-23:59"),
            ((0, 2), "DontPay - 00:00-02:59"),
            ((3, 5), "DontPay - 03:00-05:59"),
        ]

        # Find the appropriate column
        col = None
        for (start, end), column_name in time_slots:
            if start <= hour <= end or (start > end and (hour >= start or hour <= end)):
                col = column_name
                break

        if col is None:
            print("Couldn't find DontPay column that fits current time, returning None...")
            return None

        val = self.routes_df.loc[self.routes_df["route_id"] == route_id, col]
        print(f"Value of dontpay_value() for route {route_id} is {val}")
        return val.values[0] if not val.empty else None

    def get_route_id_from_trip_id(self, trip_id):
        row = self.trips_df.loc[self.trips_df["trip_id"] == trip_id, "route_id"]
        if not row.empty:
            return int(row.values[0])  # convert from numpy.int64 to Python int
        print("Row is empty, returning None...")
        return None

    # --------------------------
    # (3) Build walking network with dynamic radius + cache
    # --------------------------
    def build_walking_graph(self, center_lat, center_lon, radius_m=666, safety_buffer=120):
        # Expand a bit to avoid clipping at the edges
        effective_radius = int(radius_m + safety_buffer)
        print("Building walking graph at:", center_lat, center_lon, "radius:", radius_m)
        
        # Reuse cache if close enough and radius didn't shrink/grow a lot
        if self._cached_graph and self._cached_center and self._cached_radius:
            moved_m = self._haversine_m(center_lat, center_lon, self._cached_center[0], self._cached_center[1])
            # Reuse if center moved < 60% of radius and new radius within ±25%
            if moved_m <= 0.6 * self._cached_radius and abs(effective_radius - self._cached_radius) <= 0.25 * self._cached_radius:
                return self._cached_graph

        # Build fresh
        G = ox.graph_from_point((center_lat, center_lon), dist=effective_radius, network_type='walk')
        # Constant walking speed ~5 km/h
        nx.set_edge_attributes(G, values=5, name='speed_kph')
        G = ox.add_edge_travel_times(G)

        # Cache it
        self._cached_graph = G
        self._cached_center = (center_lat, center_lon)
        self._cached_radius = effective_radius
        return G

    # --------------------------
    # Get walking time + route using node ids (faster once we know the nodes)
    # --------------------------
    def _time_and_route_from_nodes(self, G, orig_node, dest_node):
        # Build path only when we already know time is acceptable
        path_nodes = nx.shortest_path(G, orig_node, dest_node, weight='travel_time')
        travel_time_sec = nx.shortest_path_length(G, orig_node, dest_node, weight='travel_time')

        coords = []
        for u, v in zip(path_nodes[:-1], path_nodes[1:]):
            edata = min(G.get_edge_data(u, v).values(), key=lambda x: x.get('length', 0))
            if 'geometry' in edata:
                coords.extend(list(edata['geometry'].coords))
            else:
                coords.append((G.nodes[u]['x'], G.nodes[u]['y']))
                coords.append((G.nodes[v]['x'], G.nodes[v]['y']))
        return round(travel_time_sec / 60, 2), LineString(coords)

    # --------------------------
    # (1)+(4) Find nearby stations efficiently (KDTree meters + early skip + single Dijkstra)
    # --------------------------
    def get_nearby_stations_osm(self, inspector_pos, radius_m=666, max_walk_minutes=8): #Try block needs to be added, may break
        lat, lon = inspector_pos
        sx, sy = self._to_xy_single(lat, lon)

        # 1) KDTree query in METERS
        idxs = self.kdtree.query_ball_point([sx, sy], r=radius_m)
        if not idxs:
            return []

        # Sort by straight-line distance (meters) to prioritize closer stops
        pts = self._stop_xy[idxs]                           # shape (k,2)
        dists_m = np.linalg.norm(pts - np.array([sx, sy]), axis=1)
        order = np.argsort(dists_m)
        idxs = [idxs[i] for i in order]
        dists_m = dists_m[order]

        # 2) Build walking graph sized to this query (cached)
        G = self.build_walking_graph(lat, lon, radius_m=radius_m)

        # 3) Single-source Dijkstra from inspector node → all nodes (times only)
        orig_node = ox.distance.nearest_nodes(G, lon, lat)
        time_to_node_sec = nx.single_source_dijkstra_path_length(G, orig_node, weight='travel_time')

        # 4) Batch nearest node lookup for candidate stops (fewer Python calls)
        cand_lats = self._stop_lat[idxs]
        cand_lons = self._stop_lon[idxs]
        stop_nodes = ox.distance.nearest_nodes(G, cand_lons, cand_lats)

        # 5) Early skip upper bound: straight-line time vs allowed time
        #    Upper bound walking speed: 5 km/h -> 83.33 m/min. If even the crow-fly time is too big, skip.
        max_meters_by_time = max_walk_minutes * (5000.0 / 60.0)  # ~83.33 m/min
        nearby = []

        for local_i, stop_idx in enumerate(idxs):
            if dists_m[local_i] > max_meters_by_time * 1.15:  # a small slack to avoid borderline false negatives
                continue

            s_node = stop_nodes[local_i]
            if s_node not in time_to_node_sec:
                continue  # unreachable in the walking graph

            walk_minutes_est = time_to_node_sec[s_node] / 60.0
            if walk_minutes_est > max_walk_minutes:
                continue

            # Only now compute the actual route geometry (expensive) for accepted stops
            walk_minutes, route_geom = self._time_and_route_from_nodes(G, orig_node, s_node)
            if walk_minutes <= max_walk_minutes:
                nearby.append((
                    self._stop_id[stop_idx],
                    round(walk_minutes, 2),
                    route_geom
                ))

        print(f"Nearby stations array (called from get_nearby_stations_osm):\n{nearby}")
        return sorted(nearby, key=lambda x: x[1])

    # --------------------------
    # Convert arrival time "HH:MM:SS" to minutes from now
    # --------------------------
    def minutes_until_arrival(self, arrival_time_str, now_time=None):
        if now_time is None: 
            now_time = datetime.now() #Add fake_now
        now_minutes = now_time.hour * 60 + now_time.minute + now_time.second / 60.0

        h, m, s = map(int, arrival_time_str.split(":"))
        arrival_minutes = h * 60 + m + s / 60.0
        return arrival_minutes - now_minutes

    # --------------------------
    # Find all reachable trips (uses stop_times_map for speed)
    # --------------------------
    def find_optional_lines(self, inspector_lat, inspector_lon, buffer_minutes=3, radius_m=666, max_walk_minutes=8):
        inspector_pos = (inspector_lat, inspector_lon)
        nearby_stations = self.get_nearby_stations_osm(inspector_pos, radius_m=radius_m, max_walk_minutes=max_walk_minutes)
        if not nearby_stations:
            return pd.DataFrame()

        print(f"Currently running find_optional_lines with pos {inspector_pos} on stations:\n{nearby_stations}")
        reachable = []
        for stop_id, walk_minutes, route_geom in nearby_stations:
            stop_times = self.stop_times_map.get(stop_id)
            if stop_times is None or stop_times.empty:
                continue

            # Iterate only this stop's times (no global filtering)
            for _, row in stop_times.iterrows():
                minutes_to_arrival = self.minutes_until_arrival(row['arrival_time'])
                if walk_minutes + buffer_minutes <= minutes_to_arrival:
                    reachable.append({
                        'trip_id': row['trip_id'],
                        'stop_id': stop_id,
                        'arrival_time': row['arrival_time'],
                        'walk_time': round(walk_minutes, 2),
                        'route_geometry': mapping(route_geom),
                        'minutes_until_arrival': round(minutes_to_arrival, 1)
                    })
        print(f"Reachable array (called from find_optional_lines):\n{reachable}")
        if not reachable:
            return pd.DataFrame()
        return pd.DataFrame(reachable).sort_values(by='minutes_until_arrival')

    # --------------------------
    # Find best trip for fines potential (uses avg_dont_pay_map)
    # --------------------------
    def find_best_fine_trip(self, inspector, buffer_minutes=3, radius_m=666, max_walk_minutes=8):
        if not getattr(inspector, "available", True):
            print("Inspector unavailable, exiting...")
            return None

        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute + now.second / 60

        reachable_df = self.find_optional_lines(inspector.lat, inspector.lon, buffer_minutes, radius_m, max_walk_minutes)
        if reachable_df.empty:
            print("Reachable lines empty, exiting...")
            return None

        best_option = None
        max_fines = 0
        checked_trips = set()

        for _, row in reachable_df.iterrows():
            trip_id = row['trip_id']
            if trip_id in checked_trips:
                print(f"trip_id {trip_id} was already checked, continuing...")
                continue
            checked_trips.add(trip_id)
            print(f"Added {trip_id} trip id to checked trips")

            trip_stop_times = self.stop_times_df[self.stop_times_df['trip_id'] == trip_id]
            if trip_stop_times.empty:
                print(f"trip_stop_times {trip_stop_times} is empty, continuing...")
                continue

            # Latest arrival for this trip
            try:
                latest_arrival_minutes = max([
                    int(t.split(":")[0]) * 60 + int(t.split(":")[1]) + int(t.split(":")[2]) / 60.0
                    for t in trip_stop_times['arrival_time']
                    if isinstance(t, str) and len(t.split(":")) == 3
                ])
            except Exception as e:
                print(f"Encountered exception in finding latest arrival for trip!\n{e}")
                continue
            print(f"Latest arrival minutes for trip {trip_id} is {latest_arrival_minutes}")

            time_on_board = latest_arrival_minutes - now_minutes
            if time_on_board <= 0:
                print(f"time on board is less than or equal to 0 ({time_on_board}), continuing...")
                continue
            print(f"Time on board for trip {trip_id} is {time_on_board}")

            fines_possible = int(time_on_board // 5)
            print(f"fines possible for {trip_id} is {fines_possible}")
            avg_dont_pay = self.get_dontpay_value(self.get_route_id_from_trip_id(trip_id))
            print(f"count of average non paying users for trip {trip_id} is {avg_dont_pay}")

            # #HOTFIX, IMPORTANT TO REMOVE!!! VVV
            # import random
            # avg_dont_pay = random.randrange(0, 18)
            # print(f"Randomized count of average non paying users for trip {trip_id}, now {avg_dont_pay}")
            # #HOTFIX, IMPORTANT TO REMOVE!!! ^^^

            potential_fines = min(fines_possible, int(avg_dont_pay))
            if potential_fines > max_fines:
                max_fines = potential_fines
                best_option = {
                    'trip_id': trip_id,
                    'stop_id': row['stop_id'],
                    'arrival_time': row['arrival_time'],
                    'walk_time': row['walk_time'],
                    'route_geometry': row['route_geometry'],
                    'minutes_until_arrival': row['minutes_until_arrival'],
                    'time_on_board_min': round(time_on_board, 1),
                    'AvgDontPay': avg_dont_pay,
                    'potential_fines': potential_fines
                }
            else:
                print(f"Potential fines {potential_fines} isnt bigger than max fines {max_fines}")

        print(f"Best option array (called from find_best_fine_trip):\n{best_option}")
        return best_option
    

        # --------------------------
    # Global assignment: maximize total fines across inspectors
    # --------------------------
    def assign_best_trips_global(self, inspectors, buffer_minutes=3, radius_m=666, max_walk_minutes=8):
        """
        Assigns inspectors to trips globally to maximize total fines, 
        avoiding duplicate assignments. Uses max weight bipartite matching.
        """
        import networkx as nx

        G = nx.Graph()
        trip_details = {}

        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute + now.second / 60

        # 1) Build graph edges: inspector -> trip with weight = potential_fines
        for inspector in inspectors:
            if not getattr(inspector, "available", True):
                continue

            reachable_df = self.find_optional_lines(
                inspector.lat, inspector.lon,
                buffer_minutes=buffer_minutes,
                radius_m=radius_m,
                max_walk_minutes=max_walk_minutes
            )
            if reachable_df.empty:
                continue

            for _, row in reachable_df.iterrows():
                trip_id = row["trip_id"]

                trip_stop_times = self.stop_times_df[self.stop_times_df["trip_id"] == trip_id]
                if trip_stop_times.empty:
                    continue

                try:
                    latest_arrival_minutes = max([
                        int(t.split(":")[0]) * 60 + int(t.split(":")[1]) + int(t.split(":")[2]) / 60.0
                        for t in trip_stop_times["arrival_time"]
                        if isinstance(t, str) and len(t.split(":")) == 3
                    ])
                except:
                    continue

                time_on_board = latest_arrival_minutes - now_minutes
                if time_on_board <= 0:
                    continue

                fines_possible = int(time_on_board // 5)
                avg_dont_pay = self.get_dontpay_value(self.get_route_id_from_trip_id(trip_id))
                if avg_dont_pay is None:
                    continue

                potential_fines = min(fines_possible, int(avg_dont_pay))
                if potential_fines <= 0:
                    continue

                inspector_node = f"inspector_{getattr(inspector, 'id', id(inspector))}"
                trip_node = f"trip_{trip_id}"

                G.add_edge(inspector_node, trip_node, weight=potential_fines)

                # store details for reconstruction
                trip_details[(inspector_node, trip_node)] = {
                    'trip_id': trip_id,
                    'stop_id': row['stop_id'],
                    'arrival_time': row['arrival_time'],
                    'walk_time': row['walk_time'],
                    'route_geometry': row['route_geometry'],
                    'minutes_until_arrival': row['minutes_until_arrival'],
                    'time_on_board_min': round(time_on_board, 1),
                    'AvgDontPay': avg_dont_pay,
                    'potential_fines': potential_fines,
                    'inspector_id': getattr(inspector, "id", None),
                    'inspector_lat': inspector.lat,
                    'inspector_lon': inspector.lon
                }

        if not G.edges:
            return pd.DataFrame()

        # 2) Solve maximum weight matching
        matching = nx.algorithms.matching.max_weight_matching(G, maxcardinality=True, weight="weight")

        # 3) Collect results
        results = []
        for u, v in matching:
            if u.startswith("inspector_") and v.startswith("trip_"):
                inspector_node, trip_node = u, v
            else:
                inspector_node, trip_node = v, u

            details = trip_details.get((inspector_node, trip_node))
            if details:
                results.append(details)

        return pd.DataFrame(results)
    
        # --------------------------
    # New Admin Dashboard helpers
    # --------------------------
    def get_staff_summary(self, inspectors):
        summary = []
        for i in inspectors:
            summary.append({
                "id": i.id,
                "name": i.name,
                "status": "Active" if i.active else "Offline",
                "assigned": bool(i.current_assignment),
                "assignments_today": len(getattr(i, "today_assignments", [])),
                "avg_completion_time": getattr(i, "avg_completion_time", None),
                "location": {"lat": i.lat, "lon": i.lon},
            })
        return summary

    def get_analytics_summary(self, start_date=None, end_date=None):
        # Mock data — replace with real DB or CSV lookup
        import random
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]
        return {
            "total_inspectors": random.randint(10, 20),
            "monthly_fines": {m: random.randint(100, 500) for m in months},
            "avg_violation_rate": round(random.uniform(0.1, 0.5), 2),
            "top_inspectors": [
                {"name": f"Inspector {i}", "fines": random.randint(50, 120)} for i in range(1, 6)
            ],
            "best_times": [{"hour": h, "fines": random.randint(0, 20)} for h in range(6, 24)],
        }

    def get_todays_fines(self):
        # Placeholder: replace with actual fines dataframe later
        import random
        return random.randint(30, 100)

    def check_unassigned_alerts(self, inspectors):
        unassigned = [
            {"id": i.id, "name": i.name}
            for i in inspectors
            if not i.current_assignment and i.active
        ]
        return unassigned

    def get_avg_completion_time(self, inspectors):
        times = [i.avg_completion_time for i in inspectors if getattr(i, "avg_completion_time", None)]
        if not times:
            return 0
        return round(sum(times) / len(times), 2)
