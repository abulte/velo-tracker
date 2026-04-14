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


def _build_context(goal, profile, pmc_current, start_date, start_week_type, _today: datetime.date | None = None):
    """Build the shared athlete/goal context block used in both turns."""
    today = _today or datetime.date.today()
    days_to_goal = (goal.target_date - start_date).days
    plan_weeks = min(max(1, days_to_goal // 7 + 1), 20)

    avail_lines = []
    for i in range(plan_weeks):
        ws = start_date + datetime.timedelta(weeks=i)
        week_type = "a" if (i % 2 == 0) == (start_week_type == "a") else "b"
        tmpl = (profile.week_a if week_type == "a" else profile.week_b) or {}
        hours = {d: tmpl.get(d, 0.0) for d in _DAYS}
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

def build_rationale_prompt(goal, profile, pmc_current, start_date, start_week_type) -> str:
    """Return the Turn 1 rationale prompt for preview/editing before generation."""
    context = _build_context(goal, profile, pmc_current, start_date, start_week_type)
    return _prompts.get_template("rationale.j2").render(context=context)


def generate_plan(goal, profile, pmc_current, start_date, start_week_type, rationale_prompt: str) -> PlanResult:
    """
    Two-shot plan generation:
      Turn 1 — coaching rationale (free-form analysis, streamed as text)
      Turn 2 — structured skeleton via tool use

    rationale_prompt is always the human-reviewed prompt from the UI preview step.
    Returns dict: {"rationale": str, "summary": str, "weeks": [...]}
    """
    context = _build_context(goal, profile, pmc_current, start_date, start_week_type)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # --- Turn 1: rationale ---
    log.info("=== Turn 1: rationale ===")
    r1 = _stream(client, label="coaching rationale", prompt=rationale_prompt)
    rationale = next(b.text for b in r1.content if b.type == "text")
    log.info("rationale (%d chars, stop=%s)", len(rationale), r1.stop_reason)

    # --- Turn 2: skeleton ---
    skeleton_prompt = _prompts.get_template("skeleton.j2").render(
        context=context, rationale=rationale
    )

    log.info("=== Turn 2: skeleton ===")
    r2 = _stream(client, label="plan skeleton", prompt=skeleton_prompt,
                 tools=[_SKELETON_TOOL],
                 tool_choice={"type": "tool", "name": "create_plan_skeleton"})

    if r2.stop_reason == "max_tokens":
        raise ValueError("Skeleton response truncated. Try a shorter plan horizon.")

    tool_use = next((b for b in r2.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"No tool call in skeleton response. stop_reason={r2.stop_reason}")

    skeleton = _skeleton_adapter.validate_python(tool_use.input)
    log.info("skeleton: %d weeks, stop=%s", len(skeleton["weeks"]), r2.stop_reason)
    return PlanResult(rationale=rationale, summary=skeleton["summary"], weeks=skeleton["weeks"])


def regenerate_stale_weeks(plan, stale_weeks, profile) -> PlanSkeleton:
    """
    Turn 2 only — reuses plan.rationale as prior context.
    Revises only the stale weeks and returns {"weeks": [...]} for those week numbers.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    stale_nums = sorted(w.week_number for w in stale_weeks)

    avail_lines = []
    for week in sorted(stale_weeks, key=lambda w: w.week_number):
        hours = _resolve_week_hours(week, profile)
        total_h = sum(hours.values())
        day_detail = ", ".join(
            f"{d} {hours[d]:.4g}h" for d in _DAYS if hours.get(d, 0) > 0
        )
        avail_lines.append(
            f"  Week {week.week_number}: "
            f"{total_h:.4g}h total — {day_detail if day_detail else 'no riding'}"
        )

    wpkg = f"{profile.ftp / profile.weight_kg:.2f}" if profile.ftp and profile.weight_kg else None
    prompt = _prompts.get_template("regenerate_stale.j2").render(
        ftp=profile.ftp,
        wpkg=wpkg,
        level=profile.athlete_level,
        rationale=plan.rationale or plan.summary,
        stale_nums=stale_nums,
        avail_lines=avail_lines,
    )

    log.info("=== regenerate_stale_weeks: weeks %s ===", stale_nums)
    response = _stream(client, label=f"regenerate weeks {stale_nums}", prompt=prompt,
                       tools=[_SKELETON_TOOL],
                       tool_choice={"type": "tool", "name": "create_plan_skeleton"})

    if response.stop_reason == "max_tokens":
        raise ValueError("Regenerate response truncated.")

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"No tool call in regenerate response. stop_reason={response.stop_reason}")

    skeleton = _skeleton_adapter.validate_python(tool_use.input)
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
