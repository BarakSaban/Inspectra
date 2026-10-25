import json
from pathlib import Path

import pandas as pd


def build_stop_shape_map(stop_times_df, trips_df, routes_df):
    merged = stop_times_df[['stop_id', 'trip_id']].merge(
        trips_df[['trip_id', 'route_id', 'shape_id']],
        on='trip_id',
        how='inner',
        validate='many_to_one',
    )
    merged = merged.merge(
        routes_df[['route_id', 'route_short_name', 'route_long_name']],
        on='route_id',
        how='inner',
        validate='many_to_one',
    )
    merged['shape_id'] = merged['shape_id'].astype(str).str.replace(r'\.0$', '', regex=True)
    return merged[[
        'stop_id', 'trip_id', 'route_id', 'shape_id',
        'route_short_name', 'route_long_name',
    ]].drop_duplicates().to_dict(orient='records')


def main():
    project_dir = Path(__file__).resolve().parents[2]
    gtfs_dir = project_dir / 'gtfs' / 'gtfs_filtered'
    output_path = project_dir / 'static' / 'stop_shape_map.json'

    stop_times_df = pd.read_csv(
        gtfs_dir / 'stop_times.txt',
        dtype={'stop_id': str, 'trip_id': str},
    )
    trips_df = pd.read_csv(
        gtfs_dir / 'trips.txt',
        dtype={'trip_id': str, 'route_id': str, 'shape_id': str},
    )
    routes_df = pd.read_csv(
        gtfs_dir / 'routes.txt',
        dtype={'route_id': str, 'route_short_name': str},
    )
    records = build_stop_shape_map(stop_times_df, trips_df, routes_df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as output_file:
        json.dump(records, output_file, ensure_ascii=False, indent=2)

    print(f'Saved {len(records)} verified stop-trip-route records to {output_path}')


if __name__ == '__main__':
    main()
