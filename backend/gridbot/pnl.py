"""PnL primitives; trade accounting must supply actual execution and fee records."""

from decimal import Decimal

from .errors import ValidationError
from .grid import decimal_value
from .models import Side


class PnLEngine:
    @staticmethod
    def unrealized(side: Side, qty: Decimal, average: Decimal, mark: Decimal) -> Decimal:
        qty, average, mark = (decimal_value(value) for value in (qty, average, mark))
        if qty < 0 or average <= 0 or mark <= 0:
            raise ValidationError("Input PnL non valido")
        return qty * (mark - average) * (1 if Side(side) == Side.LONG else -1)

    @staticmethod
    def realized(
        side: Side,
        qty: Decimal,
        entry: Decimal,
        exit_price: Decimal,
        entry_fees: Decimal,
        exit_fees: Decimal,
        funding: Decimal = Decimal("0"),
    ) -> dict[str, Decimal]:
        gross = PnLEngine.unrealized(side, qty, entry, exit_price)
        entry_fees, exit_fees, funding = (
            decimal_value(value) for value in (entry_fees, exit_fees, funding)
        )
        fees = entry_fees + exit_fees
        return {"realized": gross, "fees": fees, "funding": funding, "net": gross - fees + funding}


def calculate_portfolio(
    executions: list[dict],
    lots: list[dict],
    funding_events: list[dict],
    orders: list[dict],
    recovery_records: list[dict],
    market: Decimal,
) -> dict[str, Decimal]:
    """Aggregate actual ledger cash flow with persisted recovery membership.

    Recovery membership transfers the remaining original GRID entry fees once;
    already-realized GRID profit stays GRID. Funding belongs to its explicit side
    and total net but remains a separate component from GRID/RECOVERY buckets.
    """
    market = decimal_value(market, "market")
    if market <= 0:
        raise ValidationError("Prezzo portfolio non positivo")
    zero = Decimal("0")
    output = {
        key: zero
        for key in (
            "realized",
            "unrealized",
            "fees",
            "funding",
            "net",
            "grid",
            "recovery",
            "long",
            "short",
        )
    }
    order_by_link = {row.get("order_link_id", row.get("link_id")): row for row in orders}
    membership: list[tuple[int, Side, set[str]]] = []
    reclassified = zero
    seen_records: dict[tuple, Decimal] = {}
    for record in recovery_records:
        # The operational 'active' record is not a membership/cost-transfer record.
        if "activation_time_ms" not in record:
            continue
        try:
            timestamp = int(record["activation_time_ms"])
            side = Side(record["side"])
            links = record["member_links"]
            if (
                timestamp < 0
                or not isinstance(links, list)
                or any(not isinstance(link, str) or not link for link in links)
            ):
                raise ValueError("Membership Recovery incoerente")
            fees = decimal_value(record["entry_fees_reclassified"], "reclassified fees")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Membership Recovery non valida") from exc
        identity = (timestamp, side, tuple(sorted(links)))
        if identity in seen_records:
            if fees != seen_records[identity]:
                raise ValidationError("Membership Recovery duplicata con fee incoerenti")
            continue
        seen_records[identity] = fees
        membership.append((timestamp, side, set(links)))
        reclassified += fees

    def member(side: Side, link: str | None, timestamp: int | None = None) -> bool:
        return any(
            record_side == side and link in links and (timestamp is None or timestamp >= activation)
            for activation, record_side, links in membership
        )

    for execution in executions:
        try:
            side = Side(execution["side"])
            realized = decimal_value(execution["realized_pnl"], "realized pnl")
            fee = decimal_value(execution["fee"], "execution fee")
            timestamp = int(execution["time_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Execution portfolio non valida") from exc
        if timestamp < 0:
            raise ValidationError("Timestamp execution portfolio non valido")
        order = order_by_link.get(execution.get("link_id"), {})
        purpose = execution.get("purpose", order.get("purpose"))
        parent = order.get("parent_link_id")
        is_recovery = purpose in {"RECOVERY", "RECOVERY_TP"}
        if purpose == "TP" and member(side, parent, timestamp):
            is_recovery = True
        net = realized - fee
        output["realized"] += realized
        output["fees"] += fee
        output[side.value.lower()] += net
        allocations = execution.get("payload", {}).get("_allocations")
        if allocations:
            execution_qty = decimal_value(execution["qty"], "closing qty")
            allocated_qty = sum((decimal_value(row["qty"]) for row in allocations), zero)
            allocated_realized = sum(
                (decimal_value(row["realized_pnl"]) for row in allocations), zero
            )
            if (
                execution_qty <= 0
                or allocated_qty != execution_qty
                or allocated_realized != realized
            ):
                raise ValidationError("Allocazioni di chiusura portfolio incoerenti")
            allocated_fees = zero
            for index, allocation in enumerate(allocations):
                quantity = decimal_value(allocation["qty"])
                if quantity <= 0:
                    raise ValidationError("Allocazione di chiusura non positiva")
                allocation_fee = (
                    fee - allocated_fees
                    if index == len(allocations) - 1
                    else fee * quantity / execution_qty
                )
                allocated_fees += allocation_fee
                allocation_order = order_by_link.get(allocation["link_id"], {})
                recovered = (
                    is_recovery
                    or allocation_order.get("purpose") == "RECOVERY"
                    or member(side, allocation["link_id"], timestamp)
                )
                bucket = "recovery" if recovered else "grid"
                output[bucket] += decimal_value(allocation["realized_pnl"]) - allocation_fee
        else:
            output["recovery" if is_recovery else "grid"] += net

    for lot in lots:
        try:
            side = Side(lot["side"])
            unrealized = PnLEngine.unrealized(side, lot["qty"], lot["entry"], market)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Lotto portfolio non valido") from exc
        is_recovery = lot.get("purpose") == "RECOVERY" or member(side, lot.get("order_link_id"))
        output["unrealized"] += unrealized
        output[side.value.lower()] += unrealized
        output["recovery" if is_recovery else "grid"] += unrealized

    for settlement in funding_events:
        amount = decimal_value(settlement["amount"], "funding")
        output["funding"] += amount
        if settlement.get("side") in {Side.LONG.value, Side.SHORT.value}:
            output[str(settlement["side"]).lower()] += amount
    output["recovery"] -= reclassified
    output["grid"] += reclassified
    output["net"] = output["realized"] + output["unrealized"] - output["fees"] + output["funding"]
    return output


def midnight_unrealized(
    executions: list[dict],
    orders: list[dict],
    mark: Decimal,
    day_start_ms: int,
) -> Decimal:
    """Rebuild remaining executed quantity/cost at UTC midnight from the ledger.

    Entry fills after partial closes weight only the then-remaining cost. Stored
    allocation PnL identifies the consumed cost exactly; cumulative requested-order
    averages cannot reconstruct this case correctly.
    """
    mark = decimal_value(mark, "UTC midnight mark")
    if (
        mark <= 0
        or isinstance(day_start_ms, bool)
        or not isinstance(day_start_ms, int)
        or day_start_ms < 0
    ):
        raise ValidationError("Baseline UTC midnight non valida")
    by_link = {row.get("order_link_id", row.get("link_id")): row for row in orders}
    selected = []
    for execution in executions:
        try:
            timestamp = int(execution["time_ms"])
            order = by_link[execution["link_id"]]
            if timestamp < 0:
                raise ValueError("Timestamp negativo")
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError("Ledger storico incompleto per baseline UTC") from exc
        if timestamp < day_start_ms:
            selected.append((timestamp, bool(order["reduce_only"]), execution, order))
    # For equal millisecond timestamps apply actual entry fills first. Recorded
    # allocation realized PnL still removes their exact historical entry cost.
    selected.sort(key=lambda item: (item[0], item[1]))
    balances: dict[str, dict] = {}
    for _, reducing, execution, order in selected:
        try:
            qty = decimal_value(execution["qty"])
            price = decimal_value(execution["price"])
            side = Side(execution["side"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError("Ledger storico non valido") from exc
        if qty <= 0 or price <= 0:
            raise ValidationError("Execution storica non positiva")
        if not reducing:
            link = execution["link_id"]
            current = balances.setdefault(
                link, {"side": side, "qty": Decimal("0"), "cost": Decimal("0")}
            )
            if current["side"] != side:
                raise ValidationError("Execution storica cambia lato dello stesso lotto")
            current["qty"] += qty
            current["cost"] += qty * price
            continue
        allocations = execution.get("payload", {}).get("_allocations")
        if allocations:
            if sum((decimal_value(row["qty"]) for row in allocations), Decimal("0")) != qty:
                raise ValidationError("Allocazioni storiche non corrispondono alla chiusura")
            for allocation in allocations:
                q = decimal_value(allocation["qty"])
                pnl = decimal_value(allocation["realized_pnl"])
                link = allocation["link_id"]
                current = balances.get(link)
                if current is None or current["side"] != side or q <= 0 or q > current["qty"]:
                    raise ValidationError("Chiusura storica supera quantità posseduta")
                entry_cost = q * price - pnl * (1 if side == Side.LONG else -1)
                current["qty"] -= q
                current["cost"] -= entry_cost
                if current["qty"] == 0:
                    if abs(current["cost"]) > Decimal("1e-16"):
                        raise ValidationError("Costo storico residuo con quantità nulla")
                    current["cost"] = Decimal("0")
            continue
        parent = order.get("parent_link_id")
        links = (
            [parent]
            if parent
            else [link for link, value in balances.items() if value["side"] == side]
        )
        remaining = qty
        for link in links:
            current = balances.get(link)
            if current is None or current["side"] != side:
                raise ValidationError("Lotto storico della chiusura non disponibile")
            if current["qty"] == 0:
                continue
            q = min(current["qty"], remaining)
            current["cost"] -= q * current["cost"] / current["qty"]
            current["qty"] -= q
            remaining -= q
            if remaining == 0:
                break
        if remaining:
            raise ValidationError("Chiusura storica senza ledger di ingresso completo")
    total = Decimal("0")
    for current in balances.values():
        if current["qty"] < 0 or current["cost"] < 0:
            raise ValidationError("Baseline storica con quantità/costo non validi")
        total += (current["qty"] * mark - current["cost"]) * (
            1 if current["side"] == Side.LONG else -1
        )
    return total


def recovery_exit_budget(
    info: dict,
    executions: list[dict],
    orders: list[dict],
    funding_events: list[dict],
) -> Decimal:
    """Fee-equivalent budget F for the CURRENT remaining activation block.

    F = original residual GRID entry fees + actual injection entry fees
        + subsequent member exit fees - subsequent member realized PnL
        - signed side funding since activation.

    Entry fee allocations are not added again: their full activation cost already
    belongs to F. A negative F is valid after realized gains or confirmed rebates.
    """
    try:
        side = Side(info["side"])
        activation = int(info["activation_time_ms"])
        members = info["member_links"]
        injection = info["injection_id"]
        if (
            activation < 0
            or not isinstance(members, list)
            or not isinstance(injection, str)
            or not injection
            or any(not isinstance(link, str) or not link for link in members)
        ):
            raise ValueError("Blocco Recovery incoerente")
        budget = decimal_value(info["entry_fees_reclassified"], "activation entry fees")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Budget Recovery senza membership persistita valida") from exc
    member_links = set(members) | {injection}
    by_link = {row.get("order_link_id", row.get("link_id")): row for row in orders}
    for execution in executions:
        try:
            event_side = Side(execution["side"])
            timestamp = int(execution["time_ms"])
            link = execution["link_id"]
            row = by_link[link]
            fee = decimal_value(execution["fee"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Ledger incompleto per budget Recovery") from exc
        if event_side != side:
            continue
        if link == injection and not row["reduce_only"]:
            budget += fee
            continue
        if not row["reduce_only"] or timestamp < activation:
            continue
        allocations = execution.get("payload", {}).get("_allocations")
        if allocations:
            qty = decimal_value(execution["qty"])
            if (
                qty <= 0
                or sum((decimal_value(part["qty"]) for part in allocations), Decimal("0")) != qty
            ):
                raise ValidationError("Allocazioni incoerenti nel budget Recovery")
            allocated_pnl = sum(
                (decimal_value(part["realized_pnl"]) for part in allocations), Decimal("0")
            )
            if allocated_pnl != decimal_value(execution["realized_pnl"]):
                raise ValidationError("PnL allocato incoerente nel budget Recovery")
            relevant_fee = Decimal("0")
            relevant_pnl = Decimal("0")
            allocated_fees = Decimal("0")
            for index, part in enumerate(allocations):
                quantity = decimal_value(part["qty"])
                if quantity <= 0:
                    raise ValidationError("Allocazione Recovery non positiva")
                allocation_fee = (
                    fee - allocated_fees if index == len(allocations) - 1 else fee * quantity / qty
                )
                allocated_fees += allocation_fee
                if part["link_id"] in member_links:
                    relevant_fee += allocation_fee
                    relevant_pnl += decimal_value(part["realized_pnl"])
            budget += relevant_fee - relevant_pnl
        elif row.get("parent_link_id") in member_links or (
            row.get("purpose") == "RECOVERY_TP" and row.get("pair_id") == injection
        ):
            budget += fee - decimal_value(execution["realized_pnl"])
        elif row.get("purpose") == "RECOVERY_TP" and row.get("pair_id"):
            # A different activation block can have a delayed historical exit on
            # the same side; the purpose alone does not establish membership.
            continue
        elif row.get("parent_link_id") is None:
            raise ValidationError("Chiusura aggregata senza allocazioni: budget Recovery incerto")
    for settlement in funding_events:
        try:
            timestamp = int(settlement["time_ms"])
            amount = decimal_value(settlement["amount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Funding incompleto per budget Recovery") from exc
        if timestamp < activation or amount == 0:
            continue
        event_side = settlement.get("side")
        if event_side not in {Side.LONG.value, Side.SHORT.value}:
            raise ValidationError("Funding senza lato noto: budget Recovery incerto")
        if event_side == side.value:
            budget -= amount
    return budget
