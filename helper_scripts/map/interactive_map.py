import pandas as pd
import folium

# Load your filtered stops CSV
stops_df = pd.read_csv("filtered_stops.csv")

map_center = [32.0853, 34.7818]  # tel aviv
m = folium.Map(location=map_center, zoom_start=12)

# parsing stops and adding bus stop icons
for _, stop in stops_df.iterrows():
    folium.Marker(
        location=[stop['stop_lat'], stop['stop_lon']],
        popup=stop['stop_name'],
        icon=folium.Icon(color='blue', icon='bus', prefix='fa')
    ).add_to(m)

# saving to HTML and open in browser
m.save('tel_aviv_bus_stops_map.html')
print("Map saved as tel_aviv_bus_stops_map.html")
