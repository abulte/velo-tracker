# velo-tracker

Tracks bike rides synced from Garmin Connect.

## Units

- `distance`: metres (divide by 1000 for km)
- `moving_time` / `elapsed_time`: seconds
- `average_speed` / `max_speed`: m/s (multiply by 3.6 for km/h)
- `total_elevation_gain`: metres

## Fields

- `garmin_id`: Garmin Connect activity ID (string). Primary external key.
- `activity_type`: Garmin `typeKey` — `road_biking`, `gravel_cycling`, `indoor_cycling`, `e_bike_mountain`, `cycling` (generic), etc.
- `polyline`: JSON array of `[lat, lon]` pairs for the map. Stored as Postgres `jsonb`.
- `tss`: Training Stress Score (`trainingStressScore`).
- `intensity_factor`: Ratio of normalized power to FTP.
- `training_load`: Garmin's activity training load.
- `rpe`: Rate of Perceived Exertion from device (`directWorkoutRpe`, 0–100 scale).
- `feel`: Subjective feel from device (`directWorkoutFeel`, 0–100 scale, steps of 25).
- `normalized_watts`: Normalized power.

## Sync

```bash
python cli.py sync              # Last 7 days
python cli.py sync --since 2025-01-01
flask sync [--since YYYY-MM-DD]
```

- Only cycling activities (`parentTypeId == 2`). Non-cycling skipped.
- Upserts by `garmin_id` — safe to re-run.
- 3 Garmin API calls per activity (list, detail for RPE/feel, details for polyline).

## Activity types

Known cycling `typeKey` values: `road_biking`, `gravel_cycling`, `indoor_cycling`, `e_bike_mountain`, `cycling` (generic).

UI emoji: 🚴 road, 🪨 gravel, 🏠 indoor, ⚡ e-bike MTB, 🚲 generic.

## Dashboard

Weekly and monthly breakdown with per-activity-type rows (rides, distance, time, elevation, TSS, avg RPE).
