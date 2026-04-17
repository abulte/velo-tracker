from coach import PlanSkeleton, SessionData, WeekData, _min_feasible_tss, _validate_skeleton


def _session(day="mon", session_type="endurance", tss_target=50, duration_min=60, title="S") -> SessionData:
    return SessionData(
        day_of_week=day,
        session_type=session_type,
        tss_target=tss_target,
        duration_min=duration_min,
        title=title,
        notes="",
    )


def _week(week_number=1, tss_target=100, sessions=None, phase="base", description="") -> WeekData:
    return WeekData(
        week_number=week_number,
        phase=phase,
        tss_target=tss_target,
        description=description,
        sessions=sessions or [],
    )


def _skeleton(weeks) -> PlanSkeleton:
    return PlanSkeleton(summary="test", weeks=weeks)


def test_min_feasible_tss_endurance_60min():
    # 60min endurance: 20min Z1 (warmup+cooldown) + 40min Z2 floor (55%)
    # wc_tss = 20/60 * 0.275 * 100 = 9.17
    # main_tss = 40/60 * 0.55 * 100 = 36.67
    # total ~= 46
    assert _min_feasible_tss(60, "endurance") == 46


def test_min_feasible_tss_long_ride_rejects_infeasible():
    # 210min endurance should require >=~179 TSS
    min_tss = _min_feasible_tss(210, "endurance")
    assert min_tss >= 170
    assert min_tss < 200
    # S38 regression: 115 TSS is far below feasible
    assert 115 < min_tss


def test_min_feasible_tss_vo2max_210min_is_high():
    # A 210min "vo2max" session requires very high TSS — flags S47-type bug
    assert _min_feasible_tss(210, "vo2max") > 180


def test_min_feasible_tss_recovery_60min_is_low():
    # Recovery ceiling is low; Z1-focused
    assert _min_feasible_tss(60, "recovery") < 40


def test_validate_skeleton_accepts_valid_plan():
    skeleton = _skeleton([
        _week(1, tss_target=220, sessions=[
            _session("mon", "endurance", 55, 60),
            _session("wed", "endurance", 55, 60),
            _session("fri", "endurance", 110, 120),
        ]),
    ])
    assert _validate_skeleton(skeleton) == []


def test_validate_skeleton_flags_weekly_arithmetic_mismatch():
    # Week 2 regression: 410 vs 575 sum
    skeleton = _skeleton([
        _week(2, tss_target=410, sessions=[
            _session("mon", "recovery",  50,  60),
            _session("wed", "endurance", 55,  60),
            _session("thu", "threshold", 85,  60),
            _session("sat", "long",     200, 240),
            _session("sun", "long",     185, 240),
        ]),
    ])
    errors = _validate_skeleton(skeleton)
    assert any("Week 2" in e and "575" in e for e in errors)


def test_validate_skeleton_flags_infeasible_session_tss():
    # S38 regression: 115 TSS in 210min endurance is infeasible
    skeleton = _skeleton([
        _week(1, tss_target=220, sessions=[
            _session("wed", "recovery",   50,  60),
            _session("thu", "endurance",  55,  60),
            _session("fri", "endurance", 115, 210, title="Long Friday Ride"),
        ]),
    ])
    errors = _validate_skeleton(skeleton)
    assert any("Long Friday Ride" in e and "115 TSS" in e for e in errors)
    assert any("shorter sessions" in e.lower() or "reduce duration" in e for e in errors)


def test_validate_skeleton_allows_weekly_tolerance():
    # Sum 215 vs target 220 is within ±5% — should pass arithmetic
    skeleton = _skeleton([
        _week(1, tss_target=220, sessions=[
            _session("mon", "endurance", 55, 60),
            _session("wed", "endurance", 55, 60),
            _session("fri", "endurance", 105, 120),
        ]),
    ])
    # Sum = 215, diff = 5, 5/220 = 2.3% < 5% → ok
    errors = _validate_skeleton(skeleton)
    # Only check arithmetic rule here — individual feasibility may still flag, so filter:
    arith_errors = [e for e in errors if "sum(sessions)" in e]
    assert arith_errors == []


def test_validate_skeleton_surfaces_both_remedies_in_error():
    skeleton = _skeleton([
        _week(1, tss_target=115, sessions=[
            _session("fri", "endurance", 115, 210, title="TooLong"),
        ]),
    ])
    errors = _validate_skeleton(skeleton)
    msg = next(e for e in errors if "TooLong" in e)
    # Error should mention both raising TSS and reducing duration
    assert "raise tss_target" in msg
    assert "reduce duration" in msg
