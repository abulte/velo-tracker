# velo-tracker

Tracks bike rides synced from intervals.icu (which aggregates from Garmin, Strava, etc.).

## Units

- `distance`: metres (divide by 1000 for km)
- `moving_time` / `elapsed_time`: seconds
- `average_speed` / `max_speed`: m/s (multiply by 3.6 for km/h)
- `total_elevation_gain`: metres

## Fields that need context

- `icu_id`: intervals.icu activity ID, e.g. `"A12345678"`. Primary external key used in API calls and URLs.
- `athlete_id`: intervals.icu athlete ID, e.g. `"i12345"`. Matches the `INTERVALS_ATHLETE_ID` env var.
- `tss`: Training Stress Score — composite load metric (time × intensity²). Higher = harder session. Note: currently populated from the same API field as `icu_training_load`, so these two columns are identical.
- `intensity_factor`: Ratio of normalized power to the athlete's FTP. 0.75 = endurance, 1.0 = threshold, >1.0 = above FTP.
- `icu_training_load`: Same value as `tss` (both map to `icu_training_load` from the API). Redundant — one will likely be dropped.
- `icu_rpe`: Rate of Perceived Exertion, 1–10. Entered on the Garmin device after the ride.
- `feel`: Subjective feel, 1–5 (1 = terrible, 5 = great). Also entered on device.
- `normalized_watts`: Populated from `icu_weighted_avg_watts` in the API — the power-curve-weighted average that accounts for variability (always ≥ `average_watts`).
- `weighted_average_watts`: Model field that is **never populated** by sync — ignore it.

## Sport values

Known values from intervals.icu: `Ride`, `GravelRide`, `VirtualRide`, `EBikeRide`, `Run`, `TrailRun`, `Hike`, `Walk`, `Swim`, `WeightTraining`, `Workout`. The API passes through whatever Garmin/Strava reports, so others are possible.

Items with `_note` in the API response are calendar notes (not activities) and are skipped during sync.

## Sync

Manual only. Two ways to trigger:
- UI: "Sync" button on the activities page (POST `/activities/sync`), syncs last 7 days by default.
- CLI: `flask sync [--since YYYY-MM-DD]`, also defaults to 7 days ago.

No background scheduler or webhooks. Re-syncing the same date range upserts by `icu_id` (safe to re-run).
