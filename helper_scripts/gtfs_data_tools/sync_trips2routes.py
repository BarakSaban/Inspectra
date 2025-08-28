import pandas as pd
import zipfile
import os
import shutil

def filter_routes_from_zip(zip_path, output_file="filtered_routes.txt"):
    # Create a temporary extraction folder
    extract_dir = "./gtfs/gtfs_extracted/"
    filtered_dir = "./gtfs/gtfs_filtered/"
    os.makedirs(extract_dir, exist_ok=True)

    # Extract only the needed files
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        needed_files = ["routes.txt"]
        for file in needed_files:
            if file in zip_ref.namelist():
                zip_ref.extract(file, extract_dir)
            else:
                raise FileNotFoundError(f"{file} not found in GTFS zip.")

    # Load the extracted files
    trips = pd.read_csv(os.path.join(filtered_dir, "trips.txt"))
    routes = pd.read_csv(os.path.join(extract_dir, "routes.txt"))

    # Get all unique route_ids from trips
    used_route_ids = set(trips["route_id"].unique())
    print(used_route_ids)

    # Filter routes
    filtered_routes = routes[routes["route_id"].isin(used_route_ids)]

    # Save result
    filtered_routes.to_csv(output_file, index=False)

    # Cleanup: remove extraction folder
    shutil.rmtree(extract_dir)

    print(f"✅ Done! Saved filtered routes to {output_file}")

# Example usage:
gtfs_zip_path = r"./gtfs/israel-public-transportation.zip"


filter_routes_from_zip(gtfs_zip_path, "filtered_routes.txt")
