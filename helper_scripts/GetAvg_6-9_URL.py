import urllib.request
import urllib.parse
import json
import ssl
from gtfs_data_tools.gtfs_filterer import MY_ROUTE_IDS

def get_specific_workday_field(route_id):
    print(f"Running process for route id {route_id}")

    resource_id = 'e6cfac2f-979a-44fd-b439-ecb116ec0b16'
    filters = json.dumps({"RouteID": str(route_id)})
    
    params = {
        'resource_id': resource_id,
        'filters': filters
    }
    
    url = 'https://data.gov.il/api/3/action/datastore_search?' + urllib.parse.urlencode(params)
    
    # Disable SSL certificate verification TODO bring up on zoom
    context = ssl._create_unverified_context()

    with urllib.request.urlopen(url, context=context) as response:
        data = response.read()
        json_data = json.loads(data)

        records = json_data.get('result', {}).get('records', [])
        # Extract only the field "WorkDay - 06:00-08:59" from each record
        field_name = "WorkDay - 06:00-08:59"
        values = [record.get(field_name) for record in records]

        # Print each value line by line
        for val in values:
            print(val)

for route in MY_ROUTE_IDS:
    get_specific_workday_field(route)
