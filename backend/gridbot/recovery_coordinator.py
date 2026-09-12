"""Recovery orchestration; the runtime owns shared actor state."""

from __future__ import annotations

import time
from decimal import Decimal

from .errors import RecoveryError
from .models import OrderIntent, Side
from .orders import TERMINAL, client_id
from .pnl import recovery_exit_budget
from .recovery_targets import RecoveryTarget, select_recovery_tp

D = Decimal


class RecoveryCoordinatorMixin:
    async def _recovery_target(self, side: Side, lots: list[dict]) -> RecoveryTarget:
        from .grid import round_down, round_up
        from .recovery import break_even

        info = self.recovery_info[side.value]
        qty = sum((D(row["qty"]) for row in lots), D(0))
        avg = sum((D(row["qty"]) * D(row["entry"]) for row in lots), D(0)) / qty
        budget = recovery_exit_budget(
            info,
            await self.store.executions(),
            await self.store.orders(),
            await self.store.funding_events(),
        )
        mathematical = break_even(
            side,
            qty,
            avg,
            budget,
            self.account.taker_fee,
            self.config.slippage_pct / D(100),
            self.config.recovery_profit_target_usdt,
        )
        mathematical = (
            round_up(mathematical, self.instrument.tick_size)
            if side == Side.LONG
            else round_down(mathematical, self.instrument.tick_size)
        )
        retrace = self.config.recovery_retrace_pct / D(100)
        limit = D(info["activation_price"]) * (1 + retrace if side == Side.LONG else 1 - retrace)
        quote, source = select_recovery_tp(
            side,
            mathematical,
            self.instrument.tick_size,
            self.sr,
            limit,
        )
        return RecoveryTarget(quote, mathematical, budget, source)

    async def recovery_plans(self) -> list[dict]:
        if not self.price or not self.instrument:
            return []
        from .recovery import RecoveryEngine

        lots = await self.store.lots()
        plans = RecoveryEngine(self.account.taker_fee if self.account else D("0.0006")).analyze(
            lots, self.price, self.config, self.instrument
        )
        from .recovery import break_even

        for name in self.active_recovery:
            group = [r for r in lots if r["side"] == name]
            qty = sum((D(r["qty"]) for r in group), D(0))
            if not qty:
                continue
            avg = sum((D(r["qty"]) * D(r["entry"]) for r in group), D(0)) / qty
            fees = sum((D(r["fees"]) for r in group), D(0))
            info = self.recovery_info.get(name, {})
            budget = recovery_exit_budget(
                info,
                await self.store.executions(),
                await self.store.orders(),
                await self.store.funding_events(),
            )
            tp = info.get("recovery_tp")
            origin = D(info.get("activation_price", str(self.price)))
            progress = None
            if tp and D(tp) != origin:
                progress = str(
                    max(D(0), min(D(100), (self.price - origin) / (D(tp) - origin) * 100))
                )
            plans = [r for r in plans if r["side"] != name]
            plans.append(
                {
                    "side": name,
                    "qty": str(qty),
                    "notional": str(qty * avg),
                    "average": str(avg),
                    "unrealized_pnl": str(qty * (self.price - avg) * (1 if name == "LONG" else -1)),
                    "break_even": str(
                        break_even(
                            Side(name),
                            qty,
                            avg,
                            budget,
                            self.account.taker_fee,
                            self.config.slippage_pct / D(100),
                        )
                    ),
                    "tp": tp,
                    "required_qty": None,
                    "required_usdt": None,
                    "new_average": None,
                    "safe": False,
                    "reason": "Recovery attivo; grid e nuove injection sospese",
                    "progress": progress,
                    "fees": str(fees),
                    "exit_budget": str(budget),
                    "tp_source": info.get("tp_source"),
                    "profit_target": str(self.config.recovery_profit_target_usdt),
                    "active": True,
                }
            )
        return plans

    async def _auto_recovery(self) -> None:
        if not self.config.auto_recovery or self.status != "RUNNING" or self.active_recovery:
            return
        if any(
            not r["reduce_only"] and r["state"] not in TERMINAL for r in await self.store.orders()
        ):
            return
        for plan in await self.recovery_plans():
            if plan.get("safe") and plan["side"] not in self.active_recovery:
                await self._inject(Side(plan["side"]))
                break

    async def inject(self, side: Side, confirm: bool) -> dict:
        if not confirm:
            raise RecoveryError("Conferma recovery necessaria")
        async with self.lock:
            return await self._inject(side)

    async def _inject(self, side: Side) -> dict:
        if self.status != "RUNNING" or not self.reconciled:
            raise RecoveryError("Recovery richiede bot attivo e stato riconciliato")
        if self.active_recovery:
            raise RecoveryError("Injection già attiva: attendere la chiusura del blocco")
        if any(
            not r["reduce_only"] and r["state"] not in TERMINAL for r in await self.store.orders()
        ):
            raise RecoveryError(
                "Attendere la conferma di tutti gli ingressi grid prima del Recovery"
            )
        plan = next((r for r in await self.recovery_plans() if r["side"] == side.value), None)
        if not plan or not plan.get("safe"):
            raise RecoveryError("RECOVERY NON SICURO")
        qty = D(plan["required_qty"])
        intent = OrderIntent(
            environment=self.environment,
            symbol=self.config.symbol,
            order_link_id=client_id(self.session_id, "recovery", side.value, str(time.time_ns())),
            side=side,
            qty=qty,
            purpose="RECOVERY",
            slippage_pct=self.config.slippage_pct,
        )
        self.manager.risk.validate_order(
            intent, await self.risk_context(intent), self.config, self.instrument
        )
        # Keep existing TPs while injection is filling; replace only after confirmed fill.
        lots = [r for r in await self.store.lots() if r["side"] == side.value]
        info = {
            "injection_id": intent.order_link_id,
            "activation_time_ms": self.exchange_time_ms(),
            "activation_price": str(self.price),
            "plan": plan,
            "member_links": [r["order_link_id"] for r in lots],
            "entry_fees_reclassified": str(
                sum((D(r["fees"]) for r in lots if r["purpose"] == "GRID"), D(0))
            ),
            "side": side.value,
            "state": "ACTIVE",
        }
        self.active_recovery.add(side.value)
        self.recovery_info[side.value] = info
        await self.store.put_batch(
            [
                (
                    "injections",
                    intent.order_link_id,
                    {"side": side.value, "plan": plan, "state": "PENDING"},
                ),
                ("recovery_blocks", intent.order_link_id, info),
                (
                    "recovery_blocks",
                    "active",
                    {"sides": sorted(self.active_recovery), "info": self.recovery_info},
                ),
            ]
        )
        try:
            await self.manager.submit(intent)
        except Exception:
            row = await self.store.get_order(intent.order_link_id)
            if row and row["state"] == "REJECTED" and D(row["executed_qty"]) == 0:
                self.active_recovery.discard(side.value)
                self.recovery_info.pop(side.value, None)
                info = {**info, "state": "REJECTED", "entry_fees_reclassified": "0"}
                await self.store.put_batch(
                    [
                        (
                            "injections",
                            intent.order_link_id,
                            {"side": side.value, "plan": plan, "state": "REJECTED"},
                        ),
                        ("recovery_blocks", intent.order_link_id, info),
                        (
                            "recovery_blocks",
                            "active",
                            {"sides": sorted(self.active_recovery), "info": self.recovery_info},
                        ),
                    ]
                )
            raise
        await self.notify("recovery_started", f"{side.value} in recupero", {"plan": plan})
        return {"status": "INJECTION_PENDING"}

    async def _recovery_protection(self) -> None:
        for name in tuple(self.active_recovery):
            side = Side(name)
            lots = [r for r in await self.store.lots() if r["side"] == name]
            if not lots:
                self.active_recovery.remove(name)
                completed = self.recovery_info.pop(name, {})
                if completed:
                    await self.store.put(
                        "recovery_blocks",
                        completed["injection_id"],
                        {**completed, "state": "COMPLETED"},
                    )
                await self.store.put(
                    "recovery_blocks",
                    "active",
                    {"sides": sorted(self.active_recovery), "info": self.recovery_info},
                )
                await self.notify("recovery_completed", f"Recovery {name} completato", {})
                continue
            active_id = self.recovery_info.get(name, {}).get("injection_id")
            injections = [
                r
                for r in await self.store.orders()
                if r["purpose"] == "RECOVERY"
                and r["side"] == name
                and (active_id is None or r["order_link_id"] == active_id)
            ]
            if any(r["state"] not in TERMINAL for r in injections):
                continue
            if not injections:
                raise RecoveryError(
                    "Recovery interrotto prima dell’intenzione ordine; necessario review locale"
                )
            if not any(D(r["executed_qty"]) > 0 for r in injections):
                raise RecoveryError("Injection senza fill: protezione precedente mantenuta")
            # Never resize an existing recovery TP until exchange cancellation + actual
            # executions have been reconciled. One block TP after injection completes.
            previous_tps = [
                r
                for r in await self.store.orders()
                if r["purpose"] == "RECOVERY_TP"
                and r["side"] == name
                and (active_id is None or r["pair_id"] == active_id)
            ]
            recovery_tp = [r for r in previous_tps if r["state"] not in TERMINAL]
            covered = sum((D(r["qty"]) - D(r["executed_qty"]) for r in recovery_tp), D(0))
            current_qty = sum((D(r["qty"]) for r in lots), D(0))
            target = await self._recovery_target(side, lots)
            prices_safe = all(
                D(row["price"]) >= target.mathematical
                if side == Side.LONG
                else D(row["price"]) <= target.mathematical
                for row in recovery_tp
            )
            if recovery_tp and covered == current_qty and prices_safe:
                continue
            if previous_tps:
                self.recovery_info[name]["tp_generation"] = (
                    int(self.recovery_info[name].get("tp_generation", 0)) + 1
                )
                await self.store.put(
                    "recovery_blocks",
                    "active",
                    {"sides": sorted(self.active_recovery), "info": self.recovery_info},
                )
            pre_qty = sum((D(r["qty"]) for r in lots), D(0))
            await self._preflight_reductions(side, pre_qty, target.price, "RECOVERY_TP")
            await self.manager.cancel_reductions(side)
            await self._reconcile()
            lots = [r for r in await self.store.lots() if r["side"] == name]
            qty = sum((D(r["qty"]) for r in lots), D(0))
            if qty <= 0:
                continue
            target = await self._recovery_target(side, lots)
            tp = target.price
            generation = str(self.recovery_info.get(name, {}).get("tp_generation", 0))
            for index, chunk in enumerate(self._close_chunks(qty, False)):
                intent = OrderIntent(
                    environment=self.environment,
                    symbol=self.config.symbol,
                    order_link_id=client_id(
                        self.session_id,
                        "recovery-tp",
                        name,
                        injections[-1]["order_link_id"],
                        generation,
                        str(index),
                    ),
                    side=side,
                    qty=chunk,
                    price=tp,
                    order_type="Limit",
                    reduce_only=True,
                    purpose="RECOVERY_TP",
                    pair_id=active_id,
                    slippage_pct=self.config.slippage_pct,
                )
                await self.manager.submit(intent)
                await self.store.put(
                    "take_profits",
                    intent.order_link_id,
                    {"side": name, "qty": str(chunk), "price": str(tp), "recovery": True},
                )
            if name in self.recovery_info:
                self.recovery_info[name].update(
                    recovery_tp=str(tp),
                    exit_budget=str(target.budget),
                    mathematical_tp=str(target.mathematical),
                    tp_source=target.source,
                )
                await self.store.put("recovery_blocks", active_id, self.recovery_info[name])
                await self.store.put(
                    "recovery_blocks",
                    "active",
                    {"sides": sorted(self.active_recovery), "info": self.recovery_info},
                )
