from math import sqrt

class Station:
    def __init__(self, station_id, name, latitude, longitude, lines=None):
        self.station_id = station_id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.lines = lines or []

    def add_line(self, line):
        if line not in self.lines:
            self.lines.append(line)

    @property
    def position(self):
        return (self.latitude, self.longitude)

    def __repr__(self):
        return f"Station({self.station_id}, {self.name})"


class BusLine:
    def __init__(self, line_id, name):
        self.line_id = line_id
        self.name = name
        self.stations = []  # List of Station objects
        self.time_to_station = {}  # Maps station_id to time in minutes
        self.passengers_at_station = {}  # Maps station_id to estimated remaining passengers

    def add_station(self, station, time_to_reach, remaining_passengers):
        if station not in self.stations:
            self.stations.append(station)
            self.time_to_station[station.station_id] = time_to_reach
            self.passengers_at_station[station.station_id] = remaining_passengers

    def remove_station(self, station):
        if station in self.stations:
            self.stations.remove(station)
            self.time_to_station.pop(station.station_id, None)
            self.passengers_at_station.pop(station.station_id, None)

    def get_route(self):
        return [station.name for station in self.stations]

    def get_reverse_route(self):
        return [station.name for station in reversed(self.stations)]

    def remaining_passengers_at_station(self, station):
        return self.passengers_at_station.get(station.station_id, 0)

    def __repr__(self):
        return f"BusLine({self.line_id}, {self.name})"


class Inspector:
    def __init__(self, inspector_id, name, latitude, longitude):
        self.inspector_id = inspector_id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude

    @property
    def position(self):
        return (self.latitude, self.longitude)

    def __repr__(self):
        return f"Inspector({self.inspector_id}, {self.name})"
