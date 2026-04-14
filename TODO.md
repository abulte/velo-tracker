## Quality

- [x] add ruff + pyright config and type check (ignore alembic stuff)
- [x] no imports inline
- [x] extract prompts to text/jinja files
- [x] use g for session storage (pool compatible) and remove context managers
- [x] move config (model...) to config file
- [x] review generate plan prompt: rationale has way too many details and is very slow (but keep plan quality as high as possible)
- [x] review skeleton prompt quality vs speed tradeoff
- [x] review session steps prompt quality (zone-based steps, calculate_duration tool)
- [x] write sensible tests
- [ ] e2e / more complete test coverage
- [x] switch config.py back to sonnet/opus for production

## Phase 3 — Availability wiring (DONE)

- [x] `TrainingWeek.week_start` + `stale` fields
- [x] Migration: `training_week_stale` + `plan_owned_availability`
- [x] Store `week_start` at generation time
- [x] `POST /plan/weeks/<week_id>/availability` — persist override, mark stale
- [x] Stale badge on week header + stale banner at top of plan
- [x] `POST /plan/<plan_id>/regenerate-stale` — Turn 2 only, replaces stale week sessions
- [x] Delete plan feature with confirmation modal

## Enhancements

- [x] plan generation: pre-populate prompt in UI (as of today), allow human review/edit before submitting to Claude

## Phase 4 — Activity association (plan vs actual)

- [ ] `SessionCompletion` model: session_id, activity_id, status (completed/skipped/partial), actual_tss, actual_duration, notes
- [ ] migration: add `session_completion` table
- [ ] auto-matching logic: after sync, find TrainingSession on same day (±1 day) with TSS within 30%
- [ ] `GET /plan/unmatched` — HTMX panel with proposed matches
- [ ] `POST /plan/sessions/<id>/link/<activity_id>` — confirm association
- [ ] `POST /plan/sessions/<id>/skip` — mark skipped
- [ ] `POST /plan/sessions/<id>/dismiss` — dismiss proposal
- [ ] plan calendar: color-code session cards (green=completed, yellow=partial, grey=upcoming, red=missed)
- [ ] dashboard: "Today's Session" card + pending confirmations badge

## Phase 5 — Adaptive plan adjustment

- [ ] `coach.adapt_plan()`: context = last 2–4 weeks actual vs planned, current PMC vs targets; revise upcoming weeks only
- [ ] `POST /plan/adapt` — HTMX, show diff of changes with accept/reject UI
