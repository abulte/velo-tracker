"""AI coaching — training plan generation via Claude API."""
import datetime
import logging
import os

import anthropic

log = logging.getLogger(__name__)

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

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
                                    "notes": {"type": "string"},
                                },
                                "required": ["day_of_week", "session_type", "tss_target", "duration_min", "title"],
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
        "power_low":  {"type": "number", "description": "% of FTP, e.g. 0.95"},
        "power_high": {"type": "number", "description": "% of FTP, e.g. 1.05"},
        "cadence":    {"type": "integer", "description": "Target RPM (optional)"},
        "description": {"type": "string", "description": "Brief cue for this step"},
    },
    "required": ["type", "duration_sec", "power_low", "power_high"],
}

_SET_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["set"]},
        "repeat": {"type": "integer", "description": "Number of times to repeat the set"},
        "steps": {"type": "array", "items": _STEP_SCHEMA},
    },
    "required": ["type", "repeat", "steps"],
}

_STEPS_TOOL = {
    "name": "create_session_steps",
    "description": "Create structured workout steps for a single training session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "Top-level steps. Use type='set' with nested steps for repeated interval+recovery blocks.",
                "items": {"anyOf": [_STEP_SCHEMA, _SET_SCHEMA]},
            },
        },
        "required": ["steps"],
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_week_hours(week_start, avail_week, profile):
    """Return per-day hours dict for a given week, resolving A/B/custom."""
    if avail_week is None:
        return {d: 0.0 for d in _DAYS}
    if avail_week.week_type == "custom" and avail_week.hours:
        return {d: avail_week.hours.get(d, 0.0) for d in _DAYS}
    tmpl = (profile.week_a if avail_week.week_type == "a" else profile.week_b) or {}
    return {d: tmpl.get(d, 0.0) for d in _DAYS}


def _stream(client, label: str, prompt: str, **kwargs):
    """Log prompt, stream the call, print progress, return final message."""
    print(f"--- {label} ---", flush=True)
    print(prompt, flush=True)
    print("---", flush=True)
    messages = [{"role": "user", "content": prompt}]
    with client.messages.stream(messages=messages, **kwargs) as stream:
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


def _build_context(goal, profile, pmc_current, avail_weeks_map):
    """Build the shared athlete/goal context block used in both turns."""
    today = datetime.date.today()
    weeks_to_goal = max(1, (goal.target_date - today).days // 7)
    plan_weeks = min(weeks_to_goal, 20)

    monday = today - datetime.timedelta(days=today.weekday())
    avail_lines = []
    for i in range(plan_weeks):
        ws = monday + datetime.timedelta(weeks=i)
        hours = _resolve_week_hours(ws, avail_weeks_map.get(ws), profile)
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
    context = f"""ATHLETE
- FTP: {profile.ftp or 'unknown'}W{f' ({wpkg} W/kg)' if wpkg else ''}
- Weight: {f'{profile.weight_kg}kg' if profile.weight_kg else 'unknown'}
- Level: {profile.athlete_level or 'unknown'}{f' (peak CTL {profile.peak_ctl:.0f})' if profile.peak_ctl else ''}
- Fitness (CTL): {pmc_current.get('ctl', 0):.1f}  Fatigue (ATL): {pmc_current.get('atl', 0):.1f}  Form (TSB): {pmc_current.get('tsb', 0):.1f}

GOAL
- {goal.title}: {goal_type_desc}
- {plan_weeks} weeks to plan{f' (of {weeks_to_goal} total)' if weeks_to_goal > plan_weeks else ''}
{f'- Notes: {goal.notes}' if goal.notes else ''}

WEEKLY AVAILABILITY (max hours per day — sessions may be shorter)
{chr(10).join(avail_lines)}

POWER ZONES (% FTP): Z1 <55%  Z2 55–75%  Z3 75–90%  Z4 90–105%  Z5 105–120%
TSS REFERENCE: 1h Z2 ≈ 50–60 TSS · 1h threshold ≈ 90–100 TSS · 1h VO2max ≈ 110–120 TSS"""

    return context, plan_weeks

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_plan(goal, profile, pmc_current, avail_weeks_map):
    """
    Two-shot plan generation:
      Turn 1 — coaching rationale (free-form analysis, streamed as text)
      Turn 2 — structured skeleton via tool use

    Returns dict: {"rationale": str, "summary": str, "weeks": [...]}
    """
    context, plan_weeks = _build_context(goal, profile, pmc_current, avail_weeks_map)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # --- Turn 1: rationale ---
    rationale_prompt = f"""You are an expert cycling coach. Analyse this athlete and produce a detailed coaching rationale for their {plan_weeks}-week training plan.

{context}

Cover:
1. Fitness assessment — what the CTL/ATL/TSB numbers tell you right now
2. Periodization strategy — phase breakdown (base/build/peak/taper weeks) and why
3. TSS progression — starting weekly TSS, ramp rate, when to insert recovery weeks
4. Training priorities — which physiological systems to target and in what order
5. How the alternating availability pattern shapes session placement
6. Any risks or special considerations

Be specific and quantitative. This rationale will directly drive the structured plan."""

    log.info("=== Turn 1: rationale ===")
    r1 = _stream(client, label="coaching rationale", prompt=rationale_prompt,
                 model="claude-sonnet-4-6", max_tokens=4000)
    rationale = next(b.text for b in r1.content if b.type == "text")
    log.info("rationale (%d chars, stop=%s)", len(rationale), r1.stop_reason)

    # --- Turn 2: skeleton ---
    skeleton_prompt = f"""Based on your coaching rationale, create the structured training plan skeleton.

{context}

YOUR RATIONALE
{rationale}

Rules:
- Only schedule sessions on days with available hours
- Available hours per day are the MAXIMUM — session duration must not exceed them, but can be shorter based on training load
- No workout step detail — titles and types only (steps are generated separately per session)

Call the create_plan_skeleton tool."""

    log.info("=== Turn 2: skeleton ===")
    r2 = _stream(client, label="plan skeleton", prompt=skeleton_prompt,
                 model="claude-sonnet-4-6", max_tokens=32000,
                 tools=[_SKELETON_TOOL],
                 tool_choice={"type": "tool", "name": "create_plan_skeleton"})

    if r2.stop_reason == "max_tokens":
        raise ValueError("Skeleton response truncated. Try a shorter plan horizon.")

    tool_use = next((b for b in r2.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"No tool call in skeleton response. stop_reason={r2.stop_reason}")

    log.info("skeleton: %d weeks, stop=%s", len(tool_use.input.get("weeks", [])), r2.stop_reason)
    return {"rationale": rationale, **tool_use.input}


def generate_session_steps(session, week, plan, siblings=None):
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

    prompt = f"""You are an expert cycling coach. Create structured workout steps for this session.

SESSION
- Title: {session.title}
- Type: {session.session_type}
- Duration: {session.duration_min} min
- TSS target: {session.tss_target}
- Day: {session.day_of_week}, Week {week.week_number} ({week.phase} phase)
- Week focus: {week.description}
{(chr(10) + sibling_block) if sibling_block else ""}
PLAN CONTEXT
{plan.rationale or plan.summary}

Rules:
- power_low / power_high are fractions of FTP (e.g. 0.95 = 95% FTP)
- Use type="set" with repeat > 1 for repeated interval+recovery blocks (e.g. 3×(8min interval + 4min recovery) = one set with repeat=3 containing two steps)
- Warmup and cooldown are plain steps (not sets), repeat is always 1
- Total duration must equal {session.duration_min * 60} seconds (±60s): sum each plain step's duration_sec, and each set's (repeat × sum of inner step durations)
- Add a brief description cue to each step

Call the create_session_steps tool."""

    log.info("generating steps for session %d: %s", session.id, session.title)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = _stream(client, label=f"steps: {session.title}", prompt=prompt,
                       model="claude-sonnet-4-6", max_tokens=4000,
                       tools=[_STEPS_TOOL],
                       tool_choice={"type": "tool", "name": "create_session_steps"})

    if response.stop_reason == "max_tokens":
        raise ValueError("Steps response truncated.")

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"No tool call in steps response. stop_reason={response.stop_reason}")

    steps = tool_use.input["steps"]
    log.info("generated %d steps for session %d", len(steps), session.id)
    return steps
