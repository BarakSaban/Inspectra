class Station:
    def __init__(self, station_id, name, latitude, longitude, lines=None):
        self.station_id = station_id  # ID for station
        self.name = name              # Station name
        self.latitude = latitude      # latitude
        self.longitude = longitude    # longitude
        self.lines = lines or []       # List of bus lines in station

    def add_line(self, line):
        """add new bus line to station"""
        if line not in self.lines:
            self.lines.append(line)

    def __repr__(self):
        return f"Station({self.station_id}, {self.name})"

###################################

class BusLine:
    def __init__(self, line_id, name):
        self.line_id = line_id      # ID for line
        self.name = name            # Line name
        self.stations = []          # List of stations in line

    def add_station(self, station):
        """asd new station to park line"""
        if station not in self.stations:
            self.stations.append(station)

    def remove_station(self, station):
        """remove station from line"""
        if station in self.stations:
            self.stations.remove(station)

    def get_route(self):
        """return route as list of station names"""
        return [station.name for station in self.stations]

    def get_reverse_route(self):
        """return route as reverse list of station names"""
        return [station.name for station in reversed(self.stations)]

  
    def __repr__(self):
        return f"BusLine({self.line_id}, {self.name})"
