# Data

Everything the application reads at runtime besides the database. Nothing here is served to browsers.

## `gtfs/` – static timetable (GTFS)

A filtered snapshot of the national Israeli GTFS feed (Ministry of Transport) for the routes Inspectra tracks.
Rebuild it with `python tools/build_gtfs_subset.py <israel-public-transportation.zip>`.

| File | Used for |
| --- | --- |
| `routes.txt`, `trips.txt` | route ↔ trip ↔ shape ↔ direction; `route_id` is what live SIRI `line_ref` values refer to |
| `stops.txt` | stop locations; `stop_code` is the public number SIRI is queried with |
| `stop_times.txt` | scheduled arrivals, and the remaining ride time from any stop |
| `shapes.txt` | route lines drawn on the map |
| `calendar.txt` *(optional)* | which weekdays each service runs. When present, the static fallback only offers trips that run today; when absent every trip is assumed to run every day |

The committed snapshot dates from July 2025 and has no `calendar.txt`. Route ids can change between feed releases:
live buses whose `line_ref` is no longer in the feed are matched by their public bus number instead.

## `routes_with_avgs.csv` – passenger and fare-evasion averages

One row per tracked route (the `routes.txt` columns plus `NesoaRouteID`, the number before the first dash of
`route_desc`), then two columns per 3-hour slot:

- `WorkDay - HH:MM-HH:MM` – average boardings per trip on a working day
- `DontPay - HH:MM-HH:MM` – assumed non-paying passengers per trip (about 20% of the above). The routing engine
  uses the column of the current Israel hour to decide how many fines a ride can yield.

Provenance: the three morning/midday slots come from the open-data API on data.gov.il (resource
`e6cfac2f-979a-44fd-b439-ecb116ec0b16`); the remaining slots are maintained by hand because the API publishes
different time ranges. `python tools/refresh_fare_evasion.py` compares the file with the API (dry run); expect
differences, because the committed values were not produced by that exact query.
