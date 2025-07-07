# Calculate distance between two (lat, lon) positions in meters
def calculate_distance(pos1, pos2):
    lat1, lon1 = pos1
    lat2, lon2 = pos2
    return sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2) * 100000  # scaled for realism


# Calculate time for inspector to reach a station
def time_for_inspector_to_reach_station(inspector, station):
    """
    מחשב את הזמן שלוקח לפקח להגיע לתחנה, בהתחשב במרחק.
    """
    distance = calculate_distance(inspector.position, station.position)
    walking_speed = 5000 / 60  # meters per minute (~83.3)
    return distance / walking_speed


# Check if the bus is generally heading toward the inspector
def is_station_heading_towards_inspector(bus, inspector):
    """
    בודק אם הקו נוסע לכיוון של הפקח.
    """
    first_station = bus.stations[0]
    last_station = bus.stations[-1]

    dist_to_first = calculate_distance(inspector.position, first_station.position)
    dist_to_last = calculate_distance(inspector.position, last_station.position)

    return dist_to_first < dist_to_last


# Check if the inspector can catch the bus before most passengers get off
def can_inspector_get_on(bus, inspector):
    """
    בודק אם הפקח יכול להגיע לתחנה לפני שהרוב ירדו, ושהוא מספיק בזמן.
    """
    best_station = None
    best_station_time = float('inf')

    for station in bus.stations:
        inspector_time = time_for_inspector_to_reach_station(inspector, station)
        bus_arrival_time = bus.time_to_station.get(station.station_id, float('inf'))
        remaining_passengers = bus.remaining_passengers_at_station(station)

        if inspector_time <= bus_arrival_time and remaining_passengers > 0:
            if inspector_time < best_station_time:
                best_station = station
                best_station_time = inspector_time

    return (True, best_station) if best_station else (False, None)


# Return the best station (closest in time) for the inspector
def get_best_station_for_inspector(bus, inspector):
    """
    מחזיר את התחנה שהכי קרובה לפקח בזמן.
    """
    best_station = None
    best_time = float('inf')

    for station in bus.stations:
        t = time_for_inspector_to_reach_station(inspector, station)
        if t < best_time:
            best_time = t
            best_station = station

    return best_station


# Alternate logic to check if a line is passing in the inspector's general direction
def is_station_coming_towards_inspector(bus, inspector):
    """
    בודק אם קו נמצא בכיוון של הפקח.
    """
    first = bus.stations[0].position
    last = bus.stations[-1].position
    insp = inspector.position

    # Using latitude for directional logic (simplified)
    if (first[0] <= insp[0] <= last[0]) or (first[0] >= insp[0] >= last[0]):
        return True
    return False
