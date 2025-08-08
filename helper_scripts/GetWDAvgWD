
import urllib.request
import urllib.parse
import json
import ssl

def get_workday_fields(route_id, direction_number):
    print(f"\nRunning process for RouteID {route_id} with direction {direction_number}")

    route_direction = 1 if direction_number % 2 == 1 else 0

    resource_id = 'e6cfac2f-979a-44fd-b439-ecb116ec0b16'
    filters_dict = {
        "RouteID": str(route_id),
        "RouteDirection": str(route_direction),
        "Q": "4"
    }
    filters = json.dumps(filters_dict)

    context = ssl._create_unverified_context()

    limit = 100
    offset = 0
    total_records = None

    field_names = [
        "WorkDay - 06:00-08:59",
        "WorkDay - 09:00-11:59",
        "WorkDay - 12:00-14:59"
    ]

    all_results = []

    while total_records is None or offset < total_records:
        params = {
            'resource_id': resource_id,
            'filters': filters,
            'limit': limit,
            'offset': offset
        }

        url = 'https://data.gov.il/api/3/action/datastore_search?' + urllib.parse.urlencode(params)

        with urllib.request.urlopen(url, context=context) as response:
            data = response.read()
            json_data = json.loads(data)

            result = json_data.get('result', {})
            if total_records is None:
                total_records = result.get('total', 0)
                if total_records == 0:
                    print("No records found.")
                    return []

            records = result.get('records', [])
            if not records:
                break

            for record in records:
                output = {
                    "RouteID": route_id,
                    "RouteDirection": route_direction
                }
                for wanted_field in field_names:
                    matched_key = next((k for k in record.keys() if k.strip() == wanted_field), None)
                    output[wanted_field] = record.get(matched_key) if matched_key else None
                all_results.append(output)

            offset += limit

    return all_results

# Example usage:
results = get_workday_fields(10475, 1)

# Print table-like output
for row in results:
    print(row)  