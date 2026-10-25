"""Which stops can an inspector walk to, and how long does it take.

Uses the OpenStreetMap pedestrian network (via osmnx) for real street routing and falls back to straight-line
estimates when the network cannot be loaded, so recommendations keep working offline.
"""
import logging
import math
import threading

import networkx as nx
import numpy as np
import osmnx as ox
from scipy.spatial import KDTree
from shapely.geometry import LineString

from app import config
from app.utils.geo import EARTH_RADIUS_M, haversine_meters

logger = logging.getLogger(__name__)

ox.settings.cache_folder = str(config.OSM_CACHE_DIR)  # pin it: the default is relative to the working directory

WALK_SPEED_M_PER_MIN = 5000.0 / 60.0  # 5 km/h
# Straight-line walking estimates are inflated to approximate street detours when OSM is unavailable.
STRAIGHT_LINE_DETOUR_FACTOR = 1.3
# Street graphs kept in memory (most recently used first out). Inspectors spread over a city need several.
MAX_CACHED_GRAPHS = 4


class WalkingNetwork:
    def __init__(self, stops):
        """`stops`: DataFrame with stop_id, stop_lat, stop_lon."""
        self._stop_lat = stops["stop_lat"].to_numpy(dtype=float)
        self._stop_lon = stops["stop_lon"].to_numpy(dtype=float)
        self._stop_id = stops["stop_id"].to_numpy()

        # KDTree in METERS (local projection around the mean stop latitude)
        self._ref_lat_rad = math.radians(float(self._stop_lat.mean()))
        self._stop_xy = self._to_xy(self._stop_lat, self._stop_lon)
        self._kdtree = KDTree(self._stop_xy)

        # Street graphs already downloaded: [(center_lat, center_lon, radius_m, graph)], least recently used first.
        # Guarded by a lock because Flask serves requests on several threads.
        self._graph_lock = threading.Lock()
        self._graphs = []

    def _to_xy(self, lat, lon):
        x = np.radians(lon) * math.cos(self._ref_lat_rad) * EARTH_RADIUS_M
        y = np.radians(lat) * EARTH_RADIUS_M
        return np.column_stack((x, y))

    def _graph(self, center_lat, center_lon, radius_m, safety_buffer=120):
        """A walking graph covering the area, reused when a cached one is close enough, else downloaded."""
        effective_radius = int(radius_m + safety_buffer)  # expand a bit to avoid clipping at the edges

        with self._graph_lock:
            for entry in self._graphs:
                lat, lon, radius, graph = entry
                moved_m = haversine_meters(center_lat, center_lon, lat, lon)
                # Reuse if the center moved < 60% of the radius and the new radius is within +-25%
                if moved_m <= 0.6 * radius and abs(effective_radius - radius) <= 0.25 * radius:
                    self._graphs.remove(entry)
                    self._graphs.append(entry)  # most recently used goes last
                    return graph

            logger.info("Building walking graph at (%s, %s) radius=%s", center_lat, center_lon, radius_m)
            graph = ox.graph_from_point((center_lat, center_lon), dist=effective_radius, network_type='walk')
            nx.set_edge_attributes(graph, values=5, name='speed_kph')  # constant walking speed
            graph = ox.add_edge_travel_times(graph)

            self._graphs.append((center_lat, center_lon, effective_radius, graph))
            del self._graphs[:-MAX_CACHED_GRAPHS]
            return graph

    @staticmethod
    def _path_geometry(graph, path_nodes):
        coords = []
        for u, v in zip(path_nodes[:-1], path_nodes[1:]):
            edge = min(graph.get_edge_data(u, v).values(), key=lambda x: x.get('length', 0))
            if 'geometry' in edge:
                coords.extend(list(edge['geometry'].coords))
            else:
                coords.append((graph.nodes[u]['x'], graph.nodes[u]['y']))
                coords.append((graph.nodes[v]['x'], graph.nodes[v]['y']))
        return LineString(coords)

    def _walk_via_osm(self, lat, lon, idxs, dists_m, radius_m, max_walk_minutes):
        graph = self._graph(lat, lon, radius_m)

        # Single-source Dijkstra from the inspector's node to all nodes (times only)
        origin = ox.distance.nearest_nodes(graph, lon, lat)
        seconds_to_node = nx.single_source_dijkstra_path_length(graph, origin, weight='travel_time')
        stop_nodes = ox.distance.nearest_nodes(graph, self._stop_lon[idxs], self._stop_lat[idxs])

        # Even at the fastest walking speed, a stop beyond this crow-fly distance is unreachable in time.
        max_meters_by_time = max_walk_minutes * WALK_SPEED_M_PER_MIN * 1.15
        nearby = []
        for local_i, stop_idx in enumerate(idxs):
            if dists_m[local_i] > max_meters_by_time:
                continue
            seconds = seconds_to_node.get(stop_nodes[local_i])
            if seconds is None or seconds / 60.0 > max_walk_minutes:
                continue  # unreachable in the walking graph, or too far

            path = nx.shortest_path(graph, origin, stop_nodes[local_i], weight='travel_time')
            nearby.append((self._stop_id[stop_idx], round(seconds / 60, 2), self._path_geometry(graph, path)))
        return nearby

    def _walk_straight_line(self, lat, lon, idxs, dists_m, max_walk_minutes):
        nearby = []
        for local_i, stop_idx in enumerate(idxs):
            walk_minutes = dists_m[local_i] * STRAIGHT_LINE_DETOUR_FACTOR / WALK_SPEED_M_PER_MIN
            if walk_minutes > max_walk_minutes:
                continue
            geometry = LineString([(lon, lat), (self._stop_lon[stop_idx], self._stop_lat[stop_idx])])
            nearby.append((self._stop_id[stop_idx], round(float(walk_minutes), 2), geometry))
        return nearby

    def nearby_stops(self, lat, lon, radius_m=666, max_walk_minutes=8):
        """Reachable stops as (stop_id, walk_minutes, route LineString), shortest walk first."""
        point = self._to_xy(lat, lon)[0]

        idxs = self._kdtree.query_ball_point(point, r=radius_m)
        if not idxs:
            return []

        dists_m = np.linalg.norm(self._stop_xy[idxs] - point, axis=1)
        order = np.argsort(dists_m)
        idxs = [idxs[i] for i in order]
        dists_m = dists_m[order]

        try:
            nearby = self._walk_via_osm(lat, lon, idxs, dists_m, radius_m, max_walk_minutes)
        except Exception as exc:
            logger.warning("OSM walking network unavailable (%r); using straight-line walking estimates", exc)
            nearby = self._walk_straight_line(lat, lon, idxs, dists_m, max_walk_minutes)

        return sorted(nearby, key=lambda stop: stop[1])
