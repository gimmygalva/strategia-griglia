import pytest
from gridbot.errors import ValidationError
from gridbot.state_machine import exchange_state, transition


def test_exchange_ack_is_not_filled_and_full_lifecycle():
    state = "PENDING_CREATE"
    for next_state in [
        "NEW",
        "PARTIALLY_FILLED",
        "FILLED",
        "TP_PENDING",
        "TP_PARTIALLY_FILLED",
        "CLOSED",
    ]:
        state = transition(state, next_state)
    assert state == "CLOSED"
    assert transition(state, "NEW", stale_ok=True) == "CLOSED"
    with pytest.raises(ValidationError):
        transition(state, "NEW")


def test_cancel_fill_race_execution_dominates_stale_report():
    assert transition("CANCEL_PENDING", "FILLED") == "FILLED"
    assert transition("CANCELED", "PARTIALLY_FILLED") == "PARTIALLY_FILLED"
    assert transition("FILLED", "CANCELED", stale_ok=True) == "FILLED"
    assert transition("REJECTED", "NEW", stale_ok=True) == "REJECTED"
    assert exchange_state("PartiallyFilledCanceled") == "CANCELED"


@pytest.mark.parametrize("bad", ["UNKNOWN", "Suspicious", ""])
def test_unknown_states_never_silently_accepted(bad):
    with pytest.raises(ValidationError):
        exchange_state(bad)
    with pytest.raises(ValueError):
        transition("NEW", bad, stale_ok=True)
