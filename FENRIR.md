# velo-tracker

Tracks bike rides synced from Garmin Connect.

## Data source

Garmin Connect API via the `garminconnect` Python library (OAuth via `garth`).
Tokens stored locally in `garmin_tokens/` or as base64-encoded env vars on Dokku
(`GARMIN_OAUTH1_TOKEN`, `GARMIN_OAUTH2_TOKEN`).

## CLI

```bash
python cli.py login             # Authenticate with Garmin, save tokens, print dokku config:set command
python cli.py sync              # Sync last 7 days
python cli.py sync --since 2025-01-01  # Sync from a specific date
```

Also available as Flask CLI: `flask sync [--since YYYY-MM-DD]`

Default sync window is 7 days. Use `--since` to go further back.

## Sync details

- Only syncs cycling activities (`parentTypeId == 2`). Non-cycling activities are skipped.
- Upserts by `garmin_id` — safe to re-run.
- Fetches activity detail (RPE, feel) and polyline (map) per activity — 3 API calls each.
- Polyline is cached as JSON in the DB, no live API calls on page views.
- Progress is printed per activity during sync.

## Units

- `distance`: metres (divide by 1000 for km)
- `moving_time` / `elapsed_time`: seconds
- `average_speed` / `max_speed`: m/s (multiply by 3.6 for km/h)
- `total_elevation_gain`: metres

## Fields

- `garmin_id`: Garmin Connect activity ID (string). Primary external key.
- `activity_type`: Garmin `typeKey` — `road_biking`, `gravel_cycling`, `indoor_cycling`, `e_bike_mountain`, `cycling` (generic), etc.
- `polyline`: JSON array of `[lat, lon]` pairs for the map. Stored as Postgres `jsonb`.
- `tss`: Training Stress Score from Garmin (`trainingStressScore`).
- `intensity_factor`: Ratio of normalized power to FTP (`intensityFactor`).
- `training_load`: Garmin's activity training load (`activityTrainingLoad`).
- `rpe`: Rate of Perceived Exertion from Garmin device (`directWorkoutRpe`, 0–100 scale).
- `feel`: Subjective feel from Garmin device (`directWorkoutFeel`, 0–100 scale, steps of 25).
- `normalized_watts`: Normalized power (`normPower`).

## Activity types

Known cycling `typeKey` values from Garmin: `road_biking`, `gravel_cycling`, `indoor_cycling`, `e_bike_mountain`, `cycling` (generic). Others are possible.

Displayed as emoji in the UI: 🚴 road, 🪨 gravel, 🏠 indoor, ⚡ e-bike MTB, 🚲 generic.

## Dashboard

Weekly and monthly breakdown with per-activity-type rows showing rides, distance, time, elevation, TSS, and avg RPE.
