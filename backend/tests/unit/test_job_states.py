"""docs/TEST_PLAN.md 3.5 – job state machine table."""

import pytest

from app.models.job import STATUSES, TERMINAL
from app.services.jobs import TRANSITIONS, can_move

ALLOWED = [
    ("awaiting_approval", "ready"), ("awaiting_approval", "cancelled"), ("awaiting_approval", "expired"),
    ("ready", "queued"), ("ready", "cancelled"), ("queued", "connecting"), ("connecting", "backing_up"),
    ("backing_up", "checking"), ("checking", "applying"), ("checking", "blocked"), ("applying", "verifying"),
    ("applying", "rolling_back"), ("verifying", "saving"), ("verifying", "rolling_back"), ("saving", "success"),
    ("rolling_back", "rolled_back"), ("rolling_back", "failed"), ("checking", "cancelled"),
]


def test_every_status_has_a_row():
    assert set(TRANSITIONS) == set(STATUSES)


@pytest.mark.parametrize(("src", "dst"), ALLOWED)
def test_allowed(src, dst):
    assert can_move(src, dst)


@pytest.mark.parametrize("src", TERMINAL)
def test_terminal_states_never_change(src):
    assert all(not can_move(src, dst) for dst in STATUSES)


@pytest.mark.parametrize(("src", "dst"), [
    ("awaiting_approval", "queued"),  # cannot run before approval
    ("expired", "ready"), ("cancelled", "ready"),
    ("applying", "cancelled"),  # no cancel once applying
    ("verifying", "cancelled"), ("ready", "applying"),
])
def test_forbidden(src, dst):
    assert not can_move(src, dst)
