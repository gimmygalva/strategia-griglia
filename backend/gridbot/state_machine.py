from enum import StrEnum

from .errors import ValidationError


class OrderState(StrEnum):
    PENDING_CREATE = "PENDING_CREATE"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    TP_PENDING = "TP_PENDING"
    TP_PARTIALLY_FILLED = "TP_PARTIALLY_FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


TRANSITIONS = {
    OrderState.PENDING_CREATE: {
        OrderState.NEW,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCELED,
        OrderState.CANCEL_PENDING,
    },
    OrderState.NEW: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELED,
        OrderState.REJECTED,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELED,
    },
    OrderState.FILLED: {OrderState.TP_PENDING, OrderState.TP_PARTIALLY_FILLED, OrderState.CLOSED},
    OrderState.TP_PENDING: {OrderState.TP_PARTIALLY_FILLED, OrderState.CLOSED},
    OrderState.TP_PARTIALLY_FILLED: {OrderState.CLOSED},
    OrderState.CANCEL_PENDING: {
        OrderState.CANCELED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
    },
    # Cancel with a partial fill may arrive before executions; actual fill dominates stale cancel.
    OrderState.CANCELED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CLOSED},
    OrderState.REJECTED: set(),
    OrderState.CLOSED: set(),
}


def transition(current: str, target: str, *, stale_ok: bool = False) -> str:
    current_state, target_state = OrderState(current), OrderState(target)
    if current_state == target_state:
        return current_state.value
    if target_state in TRANSITIONS[current_state]:
        return target_state.value
    if stale_ok:
        # Only known delayed exchange reports can be ignored; unknown state raises above.
        return current_state.value
    raise ValidationError(f"Transizione ordine non valida: {current} -> {target}")


def exchange_state(status: str) -> str:
    states = {
        "New": "NEW",
        "Created": "NEW",
        "Untriggered": "NEW",
        "Triggered": "NEW",
        "PartiallyFilled": "PARTIALLY_FILLED",
        "Filled": "FILLED",
        "Cancelled": "CANCELED",
        "Canceled": "CANCELED",
        "PartiallyFilledCanceled": "CANCELED",
        "Rejected": "REJECTED",
        "Deactivated": "CANCELED",
    }
    if status not in states:
        raise ValidationError(f"Stato exchange sconosciuto: {status}")
    return states[status]
