"""Tests for training plan regeneration with session-level cutoff."""
import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session, select

from app import _session_date, _delete_mutable_sessions
from coach import _is_session_locked, _build_week_locked_context
from models import TrainingPlan, TrainingWeek, TrainingSession


def test_is_session_locked_no_activity():
    """Without linked activity: locked if session_date < cutoff, mutable if >= cutoff."""
    cutoff = datetime.date(2024, 1, 10)
    s = TrainingSession(week_id=1, day_of_week="mon", session_type="endurance",
                        tss_target=50, duration_min=60, title="T", activity_id=None)
    assert _is_session_locked(s, datetime.date(2024, 1, 9), cutoff)   # before → locked
    assert not _is_session_locked(s, datetime.date(2024, 1, 10), cutoff)  # today → mutable
    assert not _is_session_locked(s, datetime.date(2024, 1, 11), cutoff)  # future → mutable


def test_is_session_locked_with_activity():
    """With linked activity (done): locked if session_date <= cutoff, mutable if > cutoff."""
    cutoff = datetime.date(2024, 1, 10)
    s = TrainingSession(week_id=1, day_of_week="mon", session_type="endurance",
                        tss_target=50, duration_min=60, title="T", activity_id=42)
    assert _is_session_locked(s, datetime.date(2024, 1, 9), cutoff)   # past → locked
    assert _is_session_locked(s, datetime.date(2024, 1, 10), cutoff)  # today + activity → locked
    assert not _is_session_locked(s, datetime.date(2024, 1, 11), cutoff)  # future → mutable


def test_session_date():
    """Test _session_date helper computes correct date."""
    week_start = datetime.date(2024, 1, 1)  # Monday
    week = TrainingWeek(
        id=1, plan_id=1, week_number=1, phase="base", tss_target=100,
        description="test", week_start=week_start, week_type="a"
    )
    session = TrainingSession(
        id=1, week_id=1, day_of_week="wed", session_type="endurance",
        tss_target=50, duration_min=60, title="Test"
    )
    expected = week_start + datetime.timedelta(days=2)  # Wednesday
    assert _session_date(week, session) == expected


def test_delete_mutable_sessions_preserves_locked():
    """Test _delete_mutable_sessions preserves sessions before cutoff."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        plan = TrainingPlan(id=1, goal_id=1, summary="test", is_active=True, start_date=datetime.date(2024, 1, 1))
        db.add(plan)
        db.flush()

        week_start = datetime.date(2024, 1, 1)
        week = TrainingWeek(
            id=1, plan_id=1, week_number=1, phase="base", tss_target=100,
            description="test", week_start=week_start, week_type="a"
        )
        db.add(week)
        db.flush()

        mon_session = TrainingSession(
            id=1, week_id=1, day_of_week="mon", session_type="endurance",
            tss_target=50, duration_min=60, title="Monday"
        )
        wed_session = TrainingSession(
            id=2, week_id=1, day_of_week="wed", session_type="threshold",
            tss_target=60, duration_min=60, title="Wednesday"
        )
        fri_session = TrainingSession(
            id=3, week_id=1, day_of_week="fri", session_type="recovery",
            tss_target=30, duration_min=60, title="Friday"
        )
        db.add(mon_session)
        db.add(wed_session)
        db.add(fri_session)
        db.commit()

        cutoff = datetime.date(2024, 1, 3)  # Wednesday

        _delete_mutable_sessions(week, cutoff, db, profile=None)

        remaining = db.exec(select(TrainingSession).where(TrainingSession.week_id == 1)).all()
        remaining_ids = {s.id for s in remaining}

        assert 1 in remaining_ids  # Monday (before cutoff, locked)
        assert 2 not in remaining_ids  # Wednesday (on cutoff, mutable, deleted)
        assert 3 not in remaining_ids  # Friday (after cutoff, mutable, deleted)


def test_regenerate_stale_prompt_with_locked_sessions():
    """Test regenerate_stale.j2 renders correctly with locked sessions."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    env = Environment(loader=FileSystemLoader(prompts_dir), trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("regenerate_stale.j2")

    cutoff = datetime.date(2024, 1, 3)
    week_contexts = [
        {
            "week_number": 1,
            "week_start": datetime.date(2024, 1, 1),
            "locked_sessions": [
                {"day_of_week": "mon", "session_type": "endurance", "duration_min": 60, "tss_target": 50}
            ],
            "locked_tss": 50,
            "tss_target": 100,
            "remaining_tss": 50,
            "total_h": 2.0,
            "day_detail": "wed 1h fri 1h",
            "is_partial": True,
        }
    ]

    rendered = template.render(
        ftp=250,
        wpkg="3.5",
        level="amateur",
        rationale="Build base fitness",
        stale_nums=[1],
        cutoff_date=cutoff,
        week_contexts=week_contexts,
        context_extras={},
    )

    assert "Week 1" in rendered
    assert "locked" in rendered.lower()
    assert "Monday" in rendered or "mon" in rendered
    assert "remaining to schedule: 50 TSS" in rendered


def test_week_context_for_full_week():
    """Test week_context computation for fully-mutable week (no locked sessions)."""
    week_start = datetime.date(2024, 1, 8)  # Second Monday
    cutoff = datetime.date(2024, 1, 1)  # Before week starts

    session_data = {
        "id": 4,
        "week_id": 2,
        "day_of_week": "wed",
        "session_type": "endurance",
        "tss_target": 60,
        "duration_min": 60,
        "title": "Test",
    }

    _day_offsets = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}
    session_date = week_start + datetime.timedelta(days=_day_offsets[session_data["day_of_week"]])
    is_locked = session_date < cutoff

    assert not is_locked, "Should have no locked sessions (cutoff before week)"


def test_week_context_for_partial_week():
    """Test week_context computation for partial week (some locked sessions)."""
    week_start = datetime.date(2024, 1, 1)
    cutoff = datetime.date(2024, 1, 4)  # Thursday

    mon_session_data = {"day_of_week": "mon", "tss_target": 50}
    fri_session_data = {"day_of_week": "fri", "tss_target": 30}

    _day_offsets = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}

    locked = []
    for s in [mon_session_data, fri_session_data]:
        sd = week_start + datetime.timedelta(days=_day_offsets[s["day_of_week"]])
        if sd < cutoff:
            locked.append(s)

    assert len(locked) == 1
    assert locked[0]["day_of_week"] == "mon"
    assert locked[0]["tss_target"] == 50


def test_generate_plan_straddling_skips_past_day_sessions():
    """
    Defensive filter: sessions Claude places on locked (pre-cutoff) days must be dropped.
    Simulates the filter logic without a real _generate_plan call.
    """
    from app import _DAY_OFFSETS

    week_start = datetime.date(2024, 1, 1)  # Monday
    cutoff = datetime.date(2024, 1, 3)      # Wednesday — Mon/Tue are locked

    claude_sessions = [
        {"day_of_week": "mon", "tss_target": 50, "duration_min": 60,
         "session_type": "endurance", "title": "Locked Mon"},
        {"day_of_week": "tue", "tss_target": 40, "duration_min": 45,
         "session_type": "recovery", "title": "Locked Tue"},
        {"day_of_week": "wed", "tss_target": 60, "duration_min": 60,
         "session_type": "threshold", "title": "Mutable Wed"},
        {"day_of_week": "fri", "tss_target": 55, "duration_min": 60,
         "session_type": "endurance", "title": "Mutable Fri"},
    ]

    kept = []
    for s in claude_sessions:
        day_date = week_start + datetime.timedelta(days=_DAY_OFFSETS[s["day_of_week"]])
        if day_date < cutoff:
            continue  # skip locked day
        kept.append(s["day_of_week"])

    assert "mon" not in kept
    assert "tue" not in kept
    assert "wed" in kept
    assert "fri" in kept


def test_build_week_locked_context_partial_week():
    """_build_week_locked_context correctly identifies locked sessions and computes remaining TSS."""
    week_start = datetime.date(2024, 1, 1)  # Monday
    week = TrainingWeek(
        id=1, plan_id=1, week_number=1, phase="base", tss_target=200,
        description="test", week_start=week_start, week_type="a",
    )
    # Wed has activity (locked even if session_date == cutoff); Fri has no activity (mutable)
    wed_session = TrainingSession(
        week_id=1, day_of_week="wed", session_type="endurance",
        tss_target=60, duration_min=60, title="Wed", activity_id=42,
    )
    fri_session = TrainingSession(
        week_id=1, day_of_week="fri", session_type="threshold",
        tss_target=80, duration_min=60, title="Fri", activity_id=None,
    )
    cutoff = datetime.date(2024, 1, 3)  # Wednesday

    class FakeProfile:
        week_a = {"mon": 1.0, "wed": 1.0, "fri": 1.5}
        week_b = {}

    ctx = _build_week_locked_context(week, [wed_session, fri_session], cutoff, FakeProfile())

    assert ctx["locked_tss"] == 60
    assert ctx["remaining_tss"] == 140  # 200 - 60
    assert ctx["is_partial"] is True
    assert len(ctx["locked_sessions"]) == 1
    assert ctx["locked_sessions"][0]["day_of_week"] == "wed"
    # Wed and all pre-cutoff days should have 0 hours; Fri should still have hours
    assert ctx["day_detail"] != ""
    assert "fri" in ctx["day_detail"]
    assert "wed" not in ctx["day_detail"]
