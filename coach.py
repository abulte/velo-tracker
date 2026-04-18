"""AI coaching — training plan generation via Claude API."""
import datetime
import logging
import os
from pathlib import Path
from typing import TypedDict, NotRequired, cast

import anthropic
from anthropic.types import MessageParam, ToolParam
from jinja2 import Environment, FileSystemLoader
from pydantic import TypeAdapter

from config import ANTHROPIC_MODEL, ANTHROPIC_MAX_TOKENS, ZONE_BOUNDARIES

_prompts = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "prompts"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)

log = logging.getLogger(__name__)

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _is_session_locked(session, session_date: datetime.date, cutoff: datetime.date) -> bool:
    """Check if a session is locked (not subject to regeneration).

    Sessions are locked if:
    - They have a linked activity (activity_id) and session_date <= cutoff, OR
    - They don't have a linked activity and session_date < cutoff
    """
    if session.activity_id:
        return session_date <= cutoff
    return session_date < cutoff


def _build_week_locked_context(week, sessions: list, cutoff: datetime.date, profile) -> dict:
    """Build locked-session context for a partial week.

    Returns a dict with locked_sessions, locked_tss, remaining_tss, available hours,
    and is_partial — shared by generate_plan (straddling week) and regenerate_stale_weeks.
    """
    _day_offsets = {d: i for i, d in enumerate(_DAYS)}
    assert week.week_start is not None
    hours = dict(_resolve_week_hours(week, profile))

    locked = []
    for s in sessions:
        sd = week.week_start + datetime.timedelta(days=_day_offsets[s.day_of_week])
        if _is_session_locked(s, sd, cutoff):
            locked.append({
                "day_of_week": s.day_of_week,
                "session_type": s.session_type,
                "duration_min": s.duration_min,
                "tss_target": s.tss_target,
            })
            hours[s.day_of_week] = 0
    for j, d in enumerate(_DAYS):
        day_date = week.week_start + datetime.timedelta(days=j)
        if day_date < cutoff:
            hours[d] = 0

    locked_tss = sum(ls["tss_target"] for ls in locked)
    total_h = sum(hours.values())
    day_detail = ", ".join(f"{d} {hours[d]:.4g}h" for d in _DAYS if hours.get(d, 0) > 0) or "no riding"

    return {
        "week_number": week.week_number,
        "week_start": week.week_start,
        "locked_sessions": locked,
        "locked_tss": locked_tss,
        "tss_target": week.tss_target,
        "remaining_tss": week.tss_target - locked_tss,
        "total_h": total_h,
        "day_detail": day_detail,
        "is_partial": bool(locked),
    }


# ---------------------------------------------------------------------------
# Typed structures for plan data
# ---------------------------------------------------------------------------

class SessionData(TypedDict):
    day_of_week: str
    session_type: str
    tss_target: int
    duration_min: int
    title: str
    notes: NotRequired[str]


class WeekData(TypedDict):
    week_number: int
    phase: str
    tss_target: int
    description: str
    sessions: list[SessionData]


class PlanSkeleton(TypedDict):
    summary: str
    weeks: list[WeekData]


class PlanResult(PlanSkeleton):
    rationale: str


# ---------------------------------------------------------------------------
# Pydantic adapters — parse tool_use.input (Dict[str, object]) into types
# ---------------------------------------------------------------------------

_skeleton_adapter: TypeAdapter[PlanSkeleton] = TypeAdapter(PlanSkeleton)
_steps_adapter: TypeAdapter[list[dict[str, object]]] = TypeAdapter(list[dict[str, object]])


# ---------------------------------------------------------------------------
# Zone helpers — derived from ZONE_BOUNDARIES, used in tool schema + prompts
# ---------------------------------------------------------------------------

def _fmt_zone(name: str, lo: float | None, hi: float | None) -> str:
    lo_str = f"{int(lo * 100)}%" if lo is not None else None
    hi_str = f"{int(hi * 100)}%" if hi is not None else None
    if lo_str is None and hi_str is not None:
        return f"{name.upper()} <{hi_str}"
    if hi_str is None and lo_str is not None:
        return f"{name.upper()} >{lo_str}"
    if lo_str is not None and hi_str is not None:
        return f"{name.upper()} {lo_str}–{hi_str}"
    return name.upper()


_ZONE_ENUM: list[str] = list(ZONE_BOUNDARIES.keys())
_ZONE_DESC: str = " · ".join(_fmt_zone(k, v[0], v[1]) for k, v in ZONE_BOUNDARIES.items())

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_SKELETON_TOOL = {
    "name": "create_plan_skeleton",
    "description": "Create the structured skeleton of a periodized cycling training plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2-3 sentence overview of the plan strategy.",
            },
            "weeks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "week_number": {"type": "integer"},
                        "phase": {"type": "string", "enum": ["base", "build", "peak", "taper"]},
                        "tss_target": {"type": "integer"},
                        "description": {"type": "string"},
                        "sessions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "day_of_week": {
                                        "type": "string",
                                        "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                                    },
                                    "session_type": {
                                        "type": "string",
                                        "enum": ["endurance", "threshold", "vo2max", "recovery", "long"],
                                    },
                                    "tss_target": {"type": "integer"},
                                    "duration_min": {"type": "integer"},
                                    "title": {"type": "string"},
                                    "notes": {"type": "string", "description": "One sentence describing the session's purpose and feel — no zones, no interval prescriptions, no power targets. Describe intent and feel only (e.g. 'First structured effort of the block, legs should feel comfortably challenged')."},
                                },
                                "required": ["day_of_week", "session_type", "tss_target", "duration_min", "title", "notes"],
                            },
                        },
                    },
                    "required": ["week_number", "phase", "tss_target", "description", "sessions"],
                },
            },
        },
        "required": ["summary", "weeks"],
    },
}

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["warmup", "interval", "recovery", "cooldown", "steady"],
        },
        "duration_sec": {"type": "integer"},
        "zone": {
            "type": "string",
            "enum": _ZONE_ENUM,
            "description": f"Coggan power zone: {_ZONE_DESC}",
        },
        "cadence":    {"type": "integer", "description": "Target RPM (optional)"},
        "description": {"type": "string", "description": "Brief cue for this step"},
    },
    "required": ["type", "duration_sec", "zone"],
}

_SET_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["set"]},
        "repeat": {"type": "integer", "minimum": 2, "description": "Number of times to repeat the set — must be ≥ 2"},
        "steps": {"type": "array", "items": _STEP_SCHEMA},
    },
    "required": ["type", "repeat", "steps"],
}

_CALC_TOOL = {
    "name": "calculate_duration",
    "description": "Calculate the total duration of a proposed step list and check it against the target. Call this with your steps; if ok is true the steps will be saved as-is.",
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"anyOf": [_STEP_SCHEMA, _SET_SCHEMA]},
            },
        },
        "required": ["steps"],
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_steps_duration(steps: list[dict[str, object]]) -> int:
    """Compute total duration in seconds for a list of step dicts."""
    total = 0
    for step in steps:
        if step.get("type") == "set":
            inner = step.get("steps")
            repeat = step.get("repeat")
            if isinstance(inner, list) and isinstance(repeat, int):
                inner_sec = sum(
                    int(s["duration_sec"]) for s in inner
                    if isinstance(s, dict) and isinstance(s.get("duration_sec"), int)
                )
                total += inner_sec * repeat
        elif isinstance(dur := step.get("duration_sec"), int):
            total += dur
    return total


def _calc_steps_tss(steps: list[dict[str, object]], ftp: int) -> int:
    """
    Compute training stress score (TSS) from steps using power zones and FTP.
    TSS = (duration_sec / 3600) * Intensity Factor * 100
    where Intensity Factor = avg power / FTP
    """
    if not ftp or ftp <= 0:
        return 0

    total_tss = 0.0
    for step in steps:
        if step.get("type") == "set":
            # For sets, calculate TSS for inner steps and multiply by repeats
            inner = step.get("steps")
            repeat = step.get("repeat")
            if isinstance(inner, list) and isinstance(repeat, int):
                for inner_step in inner:
                    if isinstance(inner_step, dict):
                        step_tss = _calc_single_step_tss(inner_step, ftp)
                        total_tss += step_tss * repeat
        else:
            # Single step
            step_tss = _calc_single_step_tss(step, ftp)
            total_tss += step_tss

    return round(total_tss)


def _calc_single_step_tss(step: dict[str, object], ftp: int) -> float:
    """Calculate TSS for a single step using zone and FTP."""
    if not isinstance(step, dict):
        return 0.0

    duration_sec = step.get("duration_sec")
    if not isinstance(duration_sec, int) or duration_sec <= 0:
        return 0.0

    zone = step.get("zone")
    if not isinstance(zone, str) or zone not in ZONE_BOUNDARIES:
        return 0.0

    # Get zone boundaries as FTP fractions
    low, high = ZONE_BOUNDARIES[zone]

    # Handle unbounded zones
    if low is None:
        low = 0.0  # Z1 recovery zone starts from 0
    if high is None:
        # Z6 is unbounded; use lower bound as intensity estimate
        avg_power_frac = low
    else:
        # Use midpoint of zone as average power
        avg_power_frac = (low + high) / 2

    avg_power = ftp * avg_power_frac
    intensity_factor = avg_power / ftp

    tss = (duration_sec / 3600) * intensity_factor * 100
    return tss


# Minimum average intensity (% FTP) that each session_type's MAIN SET can realistically
# sustain. Used to derive a TSS floor per (duration, type) so the skeleton can't ask
# for a session whose TSS target is physiologically unreachable.
_TYPE_MIN_INTENSITY: dict[str, float] = {
    "recovery":  0.35,
    "endurance": 0.55,
    "long":      0.55,
    "threshold": 0.75,
    "vo2max":    0.65,
}
_WARMUP_COOLDOWN_INTENSITY = 0.275  # Z1 midpoint


def _min_feasible_tss(duration_min: int, session_type: str) -> int:
    """Minimum TSS achievable for a session of this duration and type, assuming
    a Z1 warmup+cooldown (up to 30min combined) plus a main set at the floor
    intensity of the session type."""
    min_intensity = _TYPE_MIN_INTENSITY.get(session_type, 0.55)
    wc_min = min(30, duration_min // 3)
    main_min = max(0, duration_min - wc_min)
    wc_tss = wc_min / 60 * _WARMUP_COOLDOWN_INTENSITY * 100
    main_tss = main_min / 60 * min_intensity * 100
    return round(wc_tss + main_tss)


def _validate_skeleton(skeleton: PlanSkeleton, locked_tss_by_week: dict[int, int] | None = None) -> list[str]:
    """Check internal consistency of a skeleton. Returns list of error messages
    (empty = valid). Used by the skeleton-generation retry loop.

    locked_tss_by_week: {week_number: tss} for locked (pre-cutoff) sessions that
    are not in `sessions` but count toward the week's tss_target.
    """
    errors: list[str] = []
    locked_tss_by_week = locked_tss_by_week or {}
    for week in skeleton["weeks"]:
        wn = week["week_number"]
        week_tss = week["tss_target"]
        sessions = week["sessions"]

        locked_tss = locked_tss_by_week.get(wn, 0)
        effective_sum = sum(s["tss_target"] for s in sessions) + locked_tss
        if week_tss > 0 and abs(effective_sum - week_tss) / week_tss > 0.05:
            locked_note = f" + {locked_tss} locked" if locked_tss else ""
            errors.append(
                f"Week {wn}: week tss_target={week_tss} but sum(sessions){locked_note}={effective_sum} "
                f"(off by {effective_sum - week_tss:+d}). Must match within ±5%."
            )

        for s in sessions:
            min_tss = _min_feasible_tss(s["duration_min"], s["session_type"])
            if s["tss_target"] < min_tss:
                min_intensity = _TYPE_MIN_INTENSITY.get(s["session_type"], 0.55)
                suggested_min = round(s["tss_target"] / (min_intensity * 100) * 60)
                errors.append(
                    f"Session '{s['title']}' (W{wn} {s['day_of_week']}): "
                    f"{s['tss_target']} TSS not achievable in {s['duration_min']}min {s['session_type']}. "
                    f"Minimum feasible: {min_tss} TSS. "
                    f"Choose: (a) raise tss_target to ≥{min_tss}, or (b) reduce duration to ~{suggested_min}min. "
                    f"Duration is a MAX, not a target — shorter sessions are often better for lower-TSS targets."
                )
    return errors


def _call_skeleton_with_validation(client, prompt: str, label: str, max_turns: int = 6,
                                    locked_tss_by_week: dict[int, int] | None = None) -> PlanSkeleton:
    """Call the create_plan_skeleton tool in a retry loop, validating the skeleton
    on each turn. If validation fails, feed errors back to Claude as tool_result and
    retry. Mirrors the pattern in generate_session_steps()."""
    messages: list[MessageParam] = [{"role": "user", "content": prompt}]
    last_errors: list[str] = []

    for turn in range(max_turns):
        print(f"--- {label} (turn {turn + 1}) ---", flush=True)
        if turn == 0:
            print(prompt, flush=True)
            print("---", flush=True)
        with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            tools=[_SKELETON_TOOL],
            tool_choice={"type": "tool", "name": "create_plan_skeleton"},
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "max_tokens":
            raise ValueError(f"{label}: response truncated")

        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            raise ValueError(f"{label}: no tool call. stop_reason={response.stop_reason}")

        skeleton = _skeleton_adapter.validate_python(tool_use.input)
        last_errors = _validate_skeleton(skeleton, locked_tss_by_week=locked_tss_by_week)
        print(f"  validation: {len(last_errors)} errors", flush=True)
        for err in last_errors:
            print(f"    ✗ {err}", flush=True)

        if not last_errors:
            return skeleton

        result = {"ok": False, "errors": last_errors}
        messages = cast(list[MessageParam], [
            *messages,
            {"role": "assistant", "content": list(response.content)},
            {"role": "user", "content": [{"type": "tool_result",
                                          "tool_use_id": tool_use.id,
                                          "content": str(result)}]},
        ])

    raise ValueError(
        f"{label}: skeleton failed validation after {max_turns} turns. "
        f"Last errors: {last_errors}"
    )


def _resolve_week_hours(week, profile):
    """Return per-day hours dict for a given TrainingWeek, resolving A/B/custom."""
    if week.week_type == "custom" and week.avail_override:
        return {d: week.avail_override.get(d, 0.0) for d in _DAYS}
    tmpl = (profile.week_a if week.week_type == "a" else profile.week_b) or {}
    return {d: tmpl.get(d, 0.0) for d in _DAYS}


def _stream(client, label: str, prompt: str, model: str = ANTHROPIC_MODEL, max_tokens: int = ANTHROPIC_MAX_TOKENS, **kwargs):
    """Log prompt, stream the call, print progress, return final message."""
    print(f"--- {label} ---", flush=True)
    print(prompt, flush=True)
    print("---", flush=True)
    messages = [{"role": "user", "content": prompt}]
    with client.messages.stream(messages=messages, model=model, max_tokens=max_tokens, **kwargs) as stream:
        chars = 0
        for event in stream:
            if event.type == "content_block_delta":
                delta = event.delta
                # text deltas (rationale turn)
                if delta.type == "text_delta":
                    print(delta.text, end="", flush=True)
                # tool input deltas (skeleton / steps turns)
                elif delta.type == "input_json_delta":
                    prev = chars
                    chars += len(delta.partial_json)
                    if chars // 1000 > prev // 1000:
                        print(f"  ...{chars} chars", flush=True)
        if chars:
            print(f"  done ({chars} chars total)", flush=True)
        else:
            print()  # newline after streamed text
        return stream.get_final_message()


def _build_context(goal, profile, pmc_current, start_date, start_week_type,
                   _today: datetime.date | None = None):
    """Build the shared athlete/goal context block used in both turns."""
    today = _today or datetime.date.today()
    days_to_goal = (goal.target_date - start_date).days
    plan_weeks = min(max(1, days_to_goal // 7 + 1), 20)

    # Availability grid is always Monday-aligned regardless of start_date
    week_monday = start_date - datetime.timedelta(days=start_date.weekday())

    avail_lines = []
    for i in range(plan_weeks):
        ws = week_monday + datetime.timedelta(weeks=i)
        week_type = "a" if (i % 2 == 0) == (start_week_type == "a") else "b"
        tmpl = (profile.week_a if week_type == "a" else profile.week_b) or {}
        # Zero out days outside the plan window so Claude doesn't schedule there,
        # even though the availability grid is wider (Monday-aligned weeks may
        # extend before start_date or after goal.target_date).
        hours = {
            d: (tmpl.get(d, 0.0) if start_date <= ws + datetime.timedelta(days=j) <= goal.target_date else 0.0)
            for j, d in enumerate(_DAYS)
        }
        total_h = sum(hours.values())
        day_detail = ", ".join(
            f"{d} {hours[d]:.4g}h" for d in _DAYS if hours.get(d, 0) > 0
        )
        avail_lines.append(
            f"  Week {i+1} ({ws.strftime('%-d %b')}): "
            f"{total_h:.4g}h total — {day_detail if day_detail else 'no riding'}"
        )

    goal_type_desc = {
        "race": f"prepare for a race/event on {goal.target_date.strftime('%d %b %Y')}",
        "ftp":  f"build FTP to {goal.target_ftp}W by {goal.target_date.strftime('%d %b %Y')}",
        "endurance": f"build endurance by {goal.target_date.strftime('%d %b %Y')}",
        "custom": goal.notes or f"custom goal by {goal.target_date.strftime('%d %b %Y')}",
    }.get(goal.goal_type, goal.goal_type)

    wpkg = f"{profile.ftp / profile.weight_kg:.2f}" if profile.ftp and profile.weight_kg else None
    days_until_start = (start_date - today).days
    start_note = (
        f" (plan starts in {days_until_start} days on {start_date.strftime('%d %b %Y')}; fitness metrics are as of today)"
        if days_until_start > 0 else ""
    )
    context = f"""TODAY: {today.strftime('%d %b %Y')}

ATHLETE
- FTP: {profile.ftp or 'unknown'}W{f' ({wpkg} W/kg)' if wpkg else ''}
- Weight: {f'{profile.weight_kg}kg' if profile.weight_kg else 'unknown'}
- Level: {profile.athlete_level or 'unknown'}{f' (peak CTL {profile.peak_ctl:.0f})' if profile.peak_ctl else ''}
- Fitness (CTL): {pmc_current.get('ctl', 0):.1f}  Fatigue (ATL): {pmc_current.get('atl', 0):.1f}  Form (TSB): {pmc_current.get('tsb', 0):.1f}{start_note}

GOAL
- {goal.title}: {goal_type_desc}
- Plan window: {start_date.strftime('%d %b %Y')} → {goal.target_date.strftime('%d %b %Y')} (hard boundaries — no sessions before start, no sessions after end)
{f'- Notes: {goal.notes}' if goal.notes else ''}

WEEKLY AVAILABILITY (max hours per day — sessions may be shorter)
{chr(10).join(avail_lines)}

POWER ZONES (% FTP): {_ZONE_DESC}
TSS REFERENCE: 1h Z2 ≈ 50–60 TSS · 1h threshold ≈ 90–100 TSS · 1h VO2max ≈ 110–120 TSS"""

    return context

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_rationale_prompt(goal, profile, pmc_current, start_date, start_week_type,
                            straddling_week=None, straddling_sessions: list | None = None,
                            cutoff: datetime.date | None = None) -> str:
    """Return the Turn 1 rationale prompt for preview/editing before generation."""
    context = _build_context(goal, profile, pmc_current, start_date, start_week_type)
    straddling_context = None
    if straddling_week and straddling_sessions is not None:
        effective_cutoff = cutoff or datetime.date.today()
        straddling_context = _build_week_locked_context(
            straddling_week, straddling_sessions, effective_cutoff, profile
        )
    return _prompts.get_template("rationale.j2").render(
        context=context, straddling_context=straddling_context
    )


def generate_plan(
    goal,
    profile,
    pmc_current,
    start_date,
    start_week_type,
    rationale_prompt: str,
    straddling_week=None,
    straddling_sessions: list | None = None,
    cutoff: datetime.date | None = None,
) -> PlanResult:
    """Two-shot plan generation: rationale (Turn 1) then skeleton (Turn 2).

    rationale_prompt is always the human-reviewed prompt from the UI preview step.
    """
    context = _build_context(goal, profile, pmc_current, start_date, start_week_type)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # When the plan starts mid-week, tell Claude which days are locked and how much
    # TSS is already committed so it sizes the partial week correctly.
    straddling_context = None
    if straddling_week and straddling_sessions is not None:
        effective_cutoff = cutoff or datetime.date.today()
        straddling_context = _build_week_locked_context(
            straddling_week, straddling_sessions, effective_cutoff, profile
        )

    # --- Turn 1: rationale ---
    log.info("=== Turn 1: rationale ===")
    r1 = _stream(client, label="coaching rationale", prompt=rationale_prompt)
    rationale = next(b.text for b in r1.content if b.type == "text")
    log.info("rationale (%d chars, stop=%s)", len(rationale), r1.stop_reason)

    # --- Turn 2: skeleton ---
    skeleton_prompt = _prompts.get_template("skeleton.j2").render(
        context=context, rationale=rationale, straddling_context=straddling_context
    )

    log.info("=== Turn 2: skeleton ===")
    # Claude is instructed to emit week 1's full-week tss_target (locked + new) but
    # only output mutable-day sessions; tell the validator so it checks sum+locked.
    locked_tss_by_week = {1: straddling_context["locked_tss"]} if straddling_context else None
    skeleton = _call_skeleton_with_validation(client, skeleton_prompt, label="plan skeleton",
                                              locked_tss_by_week=locked_tss_by_week)
    log.info("skeleton: %d weeks", len(skeleton["weeks"]))
    return PlanResult(rationale=rationale, summary=skeleton["summary"], weeks=skeleton["weeks"])


def regenerate_stale_weeks(
    plan,
    stale_weeks,
    profile,
    week_sessions: dict | None = None,
    cutoff_date: datetime.date | None = None,
    context_extras: dict | None = None,
) -> PlanSkeleton:
    """
    Turn 2 only — reuses plan.rationale as prior context.
    Revises only the stale weeks and returns {"weeks": [...]} for those week numbers.

    Sessions before cutoff_date are locked and preserved; only mutable days are regenerated.
    week_sessions: {week.id: [TrainingSession, ...]} — caller pre-loads sessions to avoid
    monkey-patching SQLModel instances.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    cutoff = cutoff_date or datetime.date.today()
    stale_nums = sorted(w.week_number for w in stale_weeks)

    week_contexts = []
    for week in sorted(stale_weeks, key=lambda w: w.week_number):
        sessions = (week_sessions or {}).get(week.id, [])
        week_contexts.append(_build_week_locked_context(week, sessions, cutoff, profile))

    wpkg = f"{profile.ftp / profile.weight_kg:.2f}" if profile.ftp and profile.weight_kg else None
    prompt = _prompts.get_template("regenerate_stale.j2").render(
        ftp=profile.ftp,
        wpkg=wpkg,
        level=profile.athlete_level,
        rationale=plan.rationale or plan.summary,
        stale_nums=stale_nums,
        cutoff_date=cutoff,
        week_contexts=week_contexts,
        context_extras=context_extras or {},
    )

    log.info("=== regenerate_stale_weeks: weeks %s (cutoff %s) ===", stale_nums, cutoff)
    locked_tss_by_week = {wc["week_number"]: wc["locked_tss"] for wc in week_contexts if wc["locked_tss"]}
    skeleton = _call_skeleton_with_validation(client, prompt, label=f"regenerate weeks {stale_nums}",
                                              locked_tss_by_week=locked_tss_by_week)
    log.info("regenerated %d weeks", len(skeleton["weeks"]))
    return skeleton


def generate_session_steps(session, week, plan, siblings=None) -> list[dict[str, object]]:
    """
    Generate structured workout steps for a single session on demand.

    `siblings` — other TrainingSession rows from the same week, for context.

    Returns list of step dicts.
    """
    _days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if siblings:
        all_sessions = sorted(list(siblings) + [session], key=lambda s: _days.index(s.day_of_week))
        week_lines = [
            f"  {s.day_of_week.capitalize()}: {s.session_type}, "
            f"{s.duration_min}min, {s.tss_target} TSS — {s.title}"
            + (" ← THIS SESSION" if s.id == session.id else "")
            for s in all_sessions
        ]
        sibling_block = "OTHER SESSIONS THIS WEEK\n" + "\n".join(week_lines)
    else:
        sibling_block = ""

    duration_sec = session.duration_min * 60
    warmup_sec = min(600, duration_sec // 6)
    cooldown_sec = min(600, duration_sec // 6)
    main_set_sec = duration_sec - warmup_sec - cooldown_sec

    prompt = _prompts.get_template("session_steps.j2").render(
        title=session.title,
        session_type=session.session_type,
        duration_min=session.duration_min,
        duration_sec=duration_sec,
        warmup_sec=warmup_sec,
        cooldown_sec=cooldown_sec,
        main_set_sec=main_set_sec,
        tss_target=session.tss_target,
        day_of_week=session.day_of_week,
        week_number=week.week_number,
        phase=week.phase,
        week_description=week.description,
        notes=session.notes,
        sibling_block=sibling_block,
        plan_context=plan.rationale or plan.summary,
    )

    log.info("generating steps for session %d: %s (%ds: %ds warmup, %ds main, %ds cooldown)",
             session.id, session.title, duration_sec, warmup_sec, main_set_sec, cooldown_sec)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    _tools = cast(list[ToolParam], [_CALC_TOOL])
    messages: list[MessageParam] = [{"role": "user", "content": prompt}]

    for turn in range(6):
        print(f"--- steps: {session.title} (turn {turn + 1}) ---", flush=True)
        with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            tools=_tools,
            tool_choice={"type": "auto"},
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        print(f"  stop={response.stop_reason} tools={[b.name for b in response.content if b.type == 'tool_use']}", flush=True)

        if response.stop_reason == "max_tokens":
            raise ValueError("Steps response truncated.")

        calc_call = next((b for b in response.content if b.type == "tool_use" and b.name == "calculate_duration"), None)
        if calc_call is None:
            raise ValueError(f"No tool call in steps response. stop_reason={response.stop_reason}")

        preview = _steps_adapter.validate_python(calc_call.input.get("steps", []))
        total = _calc_steps_duration(preview)
        delta = total - duration_sec
        ok = abs(delta) <= 30
        result = {"total_sec": total, "target_sec": duration_sec, "delta_sec": delta, "ok": ok}
        print(f"  calculate_duration: {total}s (target {duration_sec}s, delta {delta:+d}s)", flush=True)

        if ok:
            return preview

        messages = cast(list[MessageParam], [
            *messages,
            {"role": "assistant", "content": list(response.content)},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": calc_call.id, "content": str(result)}]},
        ])

    raise ValueError("generate_session_steps: exceeded max turns")
