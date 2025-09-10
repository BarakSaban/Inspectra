import pandas as pd
import requests
import json

# ------------------------------
# Build Routes With Averages
# ------------------------------

def extract_nesoa_id(route_desc):
    """Get digits before first dash"""
    return str(route_desc).split('-')[0].strip()

def fetch_workday_avgs(nesoa_id):
    """
    Fetch the averages from Inspectra API / URL.
    Returns a dict with WorkDay fields and DontPay (20%) rounded.
    """
    url_template = "https://data.gov.il/api/3/action/datastore_search?resource_id=e6cfac2f-979a-44fd-b439-ecb116ec0b16&filters={}"
    filters = {"RouteID": nesoa_id}
    response = requests.get(url_template.format(json.dumps(filters)))
    try:
        data = response.json()
        records = data.get("result", {}).get("records", [])
        if not records:
            rec = {}
        else:
            rec = records[0]

        # Helper: return safe int
        def safe_val(key):
            val = rec.get(key, 0)
            try:
                return int(val) if val not in (None, "", "null") else 0
            except:
                return 0

        # Extract values safely
        workday_vals = {
            "WorkDay - 00:00-03:59": safe_val("WorkDay - 00:00-03:59"),
            "WorkDay - 04:00-05:59": safe_val("WorkDay - 04:00-05:59"),
            "WorkDay - 06:00-08:59": safe_val("WorkDay - 06:00-08:59"),
            "WorkDay - 09:00-11:59": safe_val("WorkDay - 09:00-11:59"),
            "WorkDay - 12:00-14:59": safe_val("WorkDay - 12:00-14:59"),
            "WorkDay - 15:00-18:59": safe_val("WorkDay - 15:00-18:59"),
            "WorkDay - 19:00-23:59": safe_val("WorkDay - 19:00-23:59"),
        }

        # Add DontPay fields (20% of WorkDay, rounded to nearest int)
        dontpay_vals = {
            f"DontPay - {k.split(' - ')[1]}": round(v * 0.2) for k, v in workday_vals.items()
        }

        return {**workday_vals, **dontpay_vals}

    except Exception as e:
        print(f"Error fetching {nesoa_id}: {e}")
        return {
            "WorkDay - 00:00-03:59": 0,
            "WorkDay - 04:00-05:59": 0,
            "WorkDay - 06:00-08:59": 0,
            "WorkDay - 09:00-11:59": 0,
            "WorkDay - 12:00-14:59": 0,
            "WorkDay - 15:00-18:59": 0,
            "WorkDay - 19:00-23:59": 0,
            "DontPay - 00:00-03:59": 0,
            "DontPay - 04:00-05:59": 0,
            "DontPay - 06:00-08:59": 0,
            "DontPay - 09:00-11:59": 0,
            "DontPay - 12:00-14:59": 0,
            "DontPay - 15:00-18:59": 0,
            "DontPay - 19:00-23:59": 0,
        }

def build_routes_with_avgs(routes_df):
    routes_df = routes_df.copy()
    routes_df["NesoaRouteID"] = routes_df["route_desc"].apply(extract_nesoa_id)

    # Columns we want to add
    all_columns = [
        "WorkDay - 00:00-03:59",
        "WorkDay - 04:00-05:59",
        "WorkDay - 06:00-08:59",
        "WorkDay - 09:00-11:59",
        "WorkDay - 12:00-14:59",
        "WorkDay - 15:00-18:59",
        "WorkDay - 19:00-23:59",
        "DontPay - 00:00-03:59",
        "DontPay - 04:00-05:59",
        "DontPay - 06:00-08:59",
        "DontPay - 09:00-11:59",
        "DontPay - 12:00-14:59",
        "DontPay - 15:00-18:59",
        "DontPay - 19:00-23:59",
    ]

    avgs_list = []
    for nesoa_id in routes_df["NesoaRouteID"]:
        avgs = fetch_workday_avgs(nesoa_id)
        avgs_list.append(avgs)

    workday_df = pd.DataFrame(avgs_list, columns=all_columns)
    routes_df = pd.concat([routes_df.reset_index(drop=True), workday_df], axis=1)

    return routes_df

# ------------------------------
# USAGE
# ------------------------------
if __name__ == "__main__":
    # Load GTFS routes
    routes_df = pd.read_csv(r"gtfs/gtfs_filtered/routes.txt")
    routes_with_avgs = build_routes_with_avgs(routes_df)
    
    # Save to static folder
    routes_with_avgs.to_csv(r"static/routes_with_avgs.csv", index=False, encoding="utf-8-sig")
    print("Static table saved to static/routes_with_avgs.csv")
