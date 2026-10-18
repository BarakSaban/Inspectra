class Inspector:
    def __init__(self, inspector_id, name, lat, lon, available=True):
        self.inspector_id = inspector_id
        self.name = name
        self.lat = float(lat)
        self.lon = float(lon)
        self.available = available

    @property
    def position(self):
        return (self.lat, self.lon)

    def set_availability(self, status: bool):
        self.available = status

    def __repr__(self):
        return f"Inspector({self.inspector_id}, {self.name}, Available={self.available})"
