import pytest
from coach import _calc_steps_duration
from tests.factories import step, set_


def test_empty():
    assert _calc_steps_duration([]) == 0


def test_flat_steps():
    steps = [step(duration_sec=600), step(type="cooldown", duration_sec=300)]
    assert _calc_steps_duration(steps) == 900


def test_set():
    s = set_([step(duration_sec=480), step(type="recovery", duration_sec=120)], repeat=4)
    assert _calc_steps_duration([s]) == 4 * 600


def test_mixed():
    steps = [
        step(type="warmup", duration_sec=600),
        set_([step(duration_sec=300), step(type="recovery", duration_sec=120)], repeat=5),
        step(type="cooldown", duration_sec=600),
    ]
    assert _calc_steps_duration(steps) == 600 + 5 * 420 + 600


@pytest.mark.parametrize("repeat", [2, 3, 10])
def test_set_repeat(repeat):
    s = set_([step(duration_sec=600)], repeat=repeat)
    assert _calc_steps_duration([s]) == repeat * 600
