"""AI coaching — training plan generation via Claude API."""
import datetime
import logging
import os

import anthropic

log = logging.getLogger(__name__)

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_PLAN_TOOL = {
    "name": "create_training_plan",
    "description": "Create a structured periodized cycling training plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2-3 sentence overview of the plan strategy and key phases.",
            },
            "weeks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "week_number": {"type": "integer"},
                        "phase": {
                            "type": "string",
                            "enum": ["base", "build", "peak", "taper"],
                        },
                        "tss_target": {"type": "integer"},
                        "description": {
                            "type": "string",
                            "description": "One sentence describing the training focus for this week.",
                        },
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
                                    "warmup": {"type": "string"},
                                    "main_set": {"type": "string"},
                                    "cooldown": {"type": "string"},
                                    "notes": {"type": "string"},
                                },
                                "required": [
                                    "day_of_week", "session_type", "tss_target",
                                    "duration_min", "title", "warmup", "main_set", "cooldown",
                                ],
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


def _resolve_week_hours(week_start, avail_week, profile):
    """Return per-day hours dict for a given week, resolving A/B/custom."""
    if avail_week is None:
        return {d: 0.0 for d in _DAYS}
    if avail_week.week_type == "custom" and avail_week.hours:
        return {d: avail_week.hours.get(d, 0.0) for d in _DAYS}
    tmpl = (profile.week_a if avail_week.week_type == "a" else profile.week_b) or {}
    return {d: tmpl.get(d, 0.0) for d in _DAYS}


def generate_plan(goal, profile, pmc_current, avail_weeks_map):
    """
    Call Claude API to generate a training plan.

    Args:
        goal: Goal model instance
        profile: UserProfile model instance
        pmc_current: dict with keys ctl, atl, tsb (latest PMC values)
        avail_weeks_map: dict of {week_start_date: AvailabilityWeek | None}

    Returns:
        dict with keys "summary" and "weeks" (Claude tool call input)
    """
    today = datetime.date.today()
    weeks_to_goal = max(1, (goal.target_date - today).days // 7)
    plan_weeks = min(weeks_to_goal, 20)

    # Build per-week availability summary for the plan horizon
    monday = today - datetime.timedelta(days=today.weekday())
    avail_lines = []
    for i in range(plan_weeks):
        ws = monday + datetime.timedelta(weeks=i)
        hours = _resolve_week_hours(ws, avail_weeks_map.get(ws), profile)
        riding_days = [d for d in _DAYS if hours.get(d, 0) > 0]
        total_h = sum(hours.values())
        avail_lines.append(
            f"  Week {i+1} ({ws.strftime('%-d %b')}): "
            f"{total_h:.1f}h total — riding days: {', '.join(riding_days) if riding_days else 'none'}"
        )

    goal_type_desc = {
        "race": f"prepare for a race/event on {goal.target_date.strftime('%d %b %Y')}",
        "ftp": f"build FTP to {goal.target_ftp}W by {goal.target_date.strftime('%d %b %Y')}",
        "endurance": f"build endurance by {goal.target_date.strftime('%d %b %Y')}",
    }.get(goal.goal_type, goal.goal_type)

    prompt = f"""You are an expert cycling coach. Generate a {plan_weeks}-week periodized training plan.

ATHLETE PROFILE
- Current FTP: {profile.ftp or 'unknown'}W
- Current fitness (CTL): {pmc_current.get('ctl', 0):.1f}
- Current fatigue (ATL): {pmc_current.get('atl', 0):.1f}
- Current form (TSB): {pmc_current.get('tsb', 0):.1f}

GOAL
- {goal.title}: {goal_type_desc}
- Weeks to goal: {weeks_to_goal} (plan covers first {plan_weeks} weeks)
{f'- Notes: {goal.notes}' if goal.notes else ''}

WEEKLY AVAILABILITY (hours and riding days per week)
{chr(10).join(avail_lines)}

GUIDELINES
- Periodize as: base (aerobic foundation) → build (intensity) → peak (race-specific) → taper (2 weeks before goal)
- TSS ramp rate: max +10% per week; include a recovery week (−30% TSS) every 3–4 weeks
- Taper: last 2 weeks before goal, reduce volume 40–50% while keeping intensity
- Only schedule sessions on days with available hours; match session duration to available time
- Power zones (% FTP): Z1 <55%, Z2 55–75%, Z3 75–90%, Z4 90–105%, Z5 105–120%
- TSS reference: 1h Z2 ≈ 50–60 TSS, 1h threshold ≈ 90–100 TSS, 1h VO2max ≈ 110–120 TSS
- Warmup/main_set/cooldown should be concrete and actionable (specific durations and power targets)

Call the create_training_plan tool with the complete plan."""

    log.info("=== generate_plan prompt ===\n%s\n===========================", prompt)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=64000,
        tools=[_PLAN_TOOL],
        tool_choice={"type": "tool", "name": "create_training_plan"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        print("streaming plan...", flush=True)
        chars = 0
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "input_json_delta":
                prev = chars
                chars += len(event.delta.partial_json)
                if chars // 1000 > prev // 1000:
                    print(f"  ...{chars} chars received", flush=True)
        print(f"stream complete ({chars} chars total)", flush=True)
        response = stream.get_final_message()

    log.info("=== generate_plan response (stop_reason=%s) ===", response.stop_reason)
    for block in response.content:
        log.info("  block type=%s", block.type)
        if block.type == "tool_use":
            log.info("  tool input keys: %s", list(block.input.keys()))
            log.info("  weeks count: %s", len(block.input.get("weeks", [])))

    if response.stop_reason == "max_tokens":
        raise ValueError(f"Response was truncated (max_tokens). Try a shorter plan horizon.")

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise ValueError(f"Claude did not return a tool call. stop_reason={response.stop_reason}")

    return tool_use.input
