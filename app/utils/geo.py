import math

EARTH_RADIUS_M = 6371000.0


def haversine_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters between two lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def trim_shape_to_stop(shape_feature, stop_feature):
    """
    Copy of a LineString shape feature that starts at the coordinate closest to the stop.
    The input is never mutated (shape features are shared, cached objects); on any problem it is returned as is.
    """
    try:
        if not shape_feature or not stop_feature:
            return shape_feature
        coords = shape_feature.get('geometry', {}).get('coordinates', [])
        stop_coords = stop_feature.get('geometry', {}).get('coordinates')
        if len(coords) < 2 or not stop_coords or len(stop_coords) != 2:
            return shape_feature

        stop_lon, stop_lat = stop_coords
        closest = min(range(len(coords)), key=lambda i: math.hypot(coords[i][0] - stop_lon, coords[i][1] - stop_lat))
        return {**shape_feature, 'geometry': {**shape_feature['geometry'], 'coordinates': coords[closest:]}}
    except (AttributeError, TypeError, ValueError):
        return shape_feature
