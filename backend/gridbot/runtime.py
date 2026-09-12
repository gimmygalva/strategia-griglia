import asyncio
import json
import logging
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path

from . import __version__
from .closure import ClosureMixin
from .connection import AccountConnectionMixin
from .errors import (
    BotError,
    DatabaseError,
    RiskError,
)
from .models import Environment, OrderIntent, RiskContext, Side, StrategyConfig
from .orders import TERMINAL, client_id
from .persistence import Store
from .realtime import RealtimeMixin
from .recovery_coordinator import RecoveryCoordinatorMixin
from .valuation import ValuationMixin

D = Decimal


class BotRuntime(
    ClosureMixin, RecoveryCoordinatorMixin, RealtimeMixin, ValuationMixin, AccountConnectionMixin
):
    def __init__(
        self,
        data_dir: Path,
        credentials_store=None,
        adapter_factory=None,
        websocket_factory=None,
        mainnet_allowed: bool | None = None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.environment = Environment.DEMO
        self.store = None
        self.credentials_store = credentials_store
        self.adapter_factory = adapter_factory
        self.websocket_factory = websocket_factory
        self.mainnet_allowed = (
            os.getenv("ALLOW_MAINNET_TRADING", "false").lower() == "true"
            if mainnet_allowed is None
            else mainnet_allowed
        )
        self.live_confirmed = False
        self.status = "DISCONNECTED"
        self.connected = False
        self.public_connected = self.private_connected = False
        self.reconciled = False
        self.last_public = self.last_private = 0.0
        self.error = None
        self.price = None
        self.mark_price = None
        self.last_mark = 0.0
        self.account = None
        self.instrument = None
        self.adapter = self.ws = self.manager = self.grid = None
        self.config = StrategyConfig()
        self.exchange_positions = []
        self.candles = []
        self.sr = {}
        self.session_id = None
        self.wizard_completed = False
        self.lock = asyncio.Lock()
        self.listeners = set()
        self.tasks = []
        self.active_recovery = set()
        self.recovery_info = {}
        self.last_market_timestamp = None
        self.shutting_down = False

    def exchange_time_ms(self) -> int:
        return int(time.time() * 1000) + getattr(self.adapter, "clock_offset_ms", 0)

    def validate_send(self, intent: OrderIntent) -> None:
        """Synchronous veto after every await, immediately before starting HTTP."""
        now = time.monotonic()
        if intent.environment != self.environment:
            raise RiskError("Ambiente ordine incoerente")
        if not (
            self.connected
            and self.public_connected
            and self.private_connected
            and self.reconciled
            and self.manager
            and not self.manager.uncertain
            and self.price is not None
            and self.mark_price is not None
            and now - self.last_public < 15
            and now - self.last_mark < 15
            and not getattr(self.ws, "pending_funding", 0)
        ):
            raise RiskError("Stato o feed incerto prima dell'invio")
        if not intent.reduce_only and (
            self.status != "RUNNING" or (self.active_recovery and intent.purpose != "RECOVERY")
        ):
            raise RiskError("Nuovi ingressi sospesi")

    async def initialize(self):
        from .credentials import CredentialsStore
        from .exchange import create_adapter
        from .websocket import WebSocketManager

        self.credentials_store = self.credentials_store or CredentialsStore()
        self.adapter_factory = self.adapter_factory or create_adapter
        self.websocket_factory = self.websocket_factory or WebSocketManager
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        pointer = self.data_dir / "settings.json"
        if pointer.exists():
            try:
                meta = json.loads(pointer.read_text())
                self.environment = Environment(meta["environment"])
            except (ValueError, KeyError) as exc:
                raise DatabaseError("Configurazione ambiente locale incoerente") from exc
        await self._open_store()
        # Never resume entries merely because previous persisted status was running.
        self.status = "DISCONNECTED"
        self.tasks.append(asyncio.create_task(self._monitor(), name="safety-monitor"))

    async def _open_store(self):
        self.store = Store(self.data_dir / self.environment.value / "gridbot.sqlite3")
        await self.store.initialize()
        config = await self.store.get("configuration", "strategy")
        self.config = StrategyConfig.model_validate(config) if config else StrategyConfig()
        metadata = await self.store.get("configuration", "app") or {}
        self.wizard_completed = bool(metadata.get("wizard_completed"))
        self.session_id = metadata.get("session_id")
        snapshot = (
            await self.store.get("bot_sessions", self.session_id) if self.session_id else None
        )
        if snapshot:
            from .grid import GridEngine

            self.grid = GridEngine.restore(snapshot)
        recovery = await self.store.get("recovery_blocks", "active") or {}
        self.active_recovery = set(recovery.get("sides", []))
        self.recovery_info = recovery.get("info", {})

    async def _write_pointer(self):
        target = self.data_dir / "settings.json"
        tmp = self.data_dir / "settings.tmp"
        tmp.write_text(json.dumps({"environment": self.environment.value}))
        tmp.chmod(0o600)
        tmp.replace(target)

    async def notify(self, event: str, title: str, details: dict | None = None):
        payload = {
            "event": event,
            "title": title,
            "details": details or {},
            "environment": self.environment.value,
        }
        record = await self.store.put("strategy_events", uuid.uuid4().hex, payload)
        logging.getLogger("gridbot").info(
            "strategy_event",
            extra={
                "event": event,
                "environment": self.environment.value,
                "symbol": self.config.symbol,
                "correlation_id": self.session_id,
                **{key: payload["details"].get(key) for key in ("order_id", "pair_id", "level_id")},
            },
        )
        # Subscriber buffers hold latest state only, never block the strategy actor.
        for queue in tuple(self.listeners):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(record)

    async def fail_safe(self, exc: Exception):
        self.reconciled = False
        self.status = "DEGRADED"
        code = exc.code if isinstance(exc, BotError) else "INTERNAL_ERROR"
        self.error = str(exc) if isinstance(exc, BotError) else "Errore interno: strategia sospesa"
        try:
            await self.store.put("errors", uuid.uuid4().hex, {"code": code, "message": self.error})
            await self.notify(
                "safety_pause",
                "Strategia sospesa per sicurezza",
                {"code": code, "message": self.error},
            )
        except Exception as storage_exc:
            # Trading remains blocked even if recording the failure is unavailable.
            self.error = f"{self.error}; database non disponibile"
            import logging

            logging.getLogger("gridbot").error(
                "database_failure_during_pause",
                extra={
                    "event": "database_failure",
                    "environment": self.environment.value,
                    "error_type": type(storage_exc).__name__,
                },
            )

    async def configure(self, config: StrategyConfig):
        async with self.lock:
            if (self.status == "RUNNING" or self.active_recovery) and config.model_dump(
                exclude={"auto_recovery"}
            ) != self.config.model_dump(exclude={"auto_recovery"}):
                raise RiskError("Con bot o recovery attivi è modificabile soltanto Auto Recovery")
            if await self.store.lots() and config.tp_pct != self.config.tp_pct:
                raise RiskError("TP modificabile solo senza posizioni aperte")
            reset_grid = (
                config.spacing_pct != self.config.spacing_pct
                or config.levels != self.config.levels
                or config.hysteresis_ticks != self.config.hysteresis_ticks
                or config.debounce_ms != self.config.debounce_ms
            )
            previous = self.config.model_dump(mode="json")
            updated = config.model_dump(mode="json")
            changes = {
                name: {"before": previous[name], "after": updated[name]}
                for name, value in config.model_dump().items()
                if value != getattr(self.config, name)
            }
            await self.store.put_batch(
                [
                    ("configuration", "strategy", updated),
                    (
                        "configuration",
                        "app",
                        {
                            "wizard_completed": self.wizard_completed,
                            "session_id": None if reset_grid else self.session_id,
                        },
                    ),
                ]
            )
            self.config = config
            if reset_grid:
                self.grid = None
                self.session_id = None
            if self.manager:
                self.manager.config = config
            await self.notify("settings_changed", "Impostazioni aggiornate", {"changes": changes})

    async def risk_context(self, intent: OrderIntent) -> RiskContext:
        lots = await self.store.lots()
        orders = await self.store.orders()
        price = self.price or D(0)
        exposure = sum((D(r["qty"]) * price for r in lots), D(0))
        reservations = sum(
            (
                (D(r["qty"]) - D(r["executed_qty"])) * (D(r["price"]) if r["price"] else price)
                for r in orders
                if not r["reduce_only"] and r["state"] not in TERMINAL
            ),
            D(0),
        )
        recovery = sum(
            (
                D(r["qty"]) * price
                for r in lots
                if r["purpose"] == "RECOVERY"
                or r["side"] in self.active_recovery
                or (intent.purpose == "RECOVERY" and r["side"] == intent.side.value)
            ),
            D(0),
        )
        portfolio = await self.portfolio(lots)
        owned = sum(
            (
                D(r["qty"])
                for r in lots
                if r["side"] == intent.side.value
                and (not intent.parent_link_id or r["order_link_id"] == intent.parent_link_id)
            ),
            D(0),
        )
        if intent.reduce_only:
            covered = sum(
                (
                    D(r["qty"]) - D(r["executed_qty"])
                    for r in orders
                    if r["reduce_only"]
                    and r["side"] == intent.side.value
                    and r["state"] not in TERMINAL
                    and (
                        not intent.parent_link_id
                        or r.get("parent_link_id") == intent.parent_link_id
                    )
                ),
                D(0),
            )
            owned = max(D(0), owned - covered)
        fresh_public = time.monotonic() - self.last_public < 15
        fresh_mark = self.mark_price is not None and time.monotonic() - self.last_mark < 15
        return RiskContext(
            environment=self.environment,
            connected=self.connected
            and self.public_connected
            and self.private_connected
            and fresh_public
            and fresh_mark
            and not getattr(self.ws, "pending_funding", 0),
            running=self.status == "RUNNING"
            and (intent.purpose == "RECOVERY" or not self.active_recovery),
            reconciled=self.reconciled and not self.manager.uncertain,
            permissions=bool(self.account and self.account.permissions),
            hedge_mode=bool(self.account and self.account.hedge_mode),
            available_balance=self.account.available_balance if self.account else D(0),
            total_exposure=exposure,
            recovery_exposure=recovery,
            daily_pnl=D(portfolio["today"] or "0"),
            market_price=price,
            reserved_notional=reservations,
            mainnet_allowed=self.mainnet_allowed,
            live_confirmed=self.live_confirmed,
            position_qty=owned,
            taker_fee=self.account.taker_fee if self.account else D("0.0006"),
        )

    async def start(self, live_confirm=None, live_ack=False):
        from .grid import GridEngine

        async with self.lock:
            if self.status == "RUNNING":
                return
            if not self.connected or not self.public_connected or not self.private_connected:
                raise RiskError("Feed pubblico e privato devono essere connessi")
            if self.environment == Environment.MAINNET:
                if not self.mainnet_allowed or live_confirm != "AVVIA LIVE" or not live_ack:
                    raise RiskError("LIVE richiede flag backend e doppia conferma esplicita")
                self.live_confirmed = True
                self.adapter.set_live_authorization(self.mainnet_allowed, True)
            try:
                self.status = "RECONCILING"
                await self._reconcile()
                if (
                    self.account.leverage_long != self.config.leverage
                    or self.account.leverage_short != self.config.leverage
                ):
                    if await self.store.lots():
                        raise RiskError(
                            "Leva differente con posizioni aperte: modificare su Bybit e riconnettere"
                        )
                    await self.adapter.set_leverage(self.config.symbol, self.config.leverage)
                    self.account = await self.adapter.account()
                    if (
                        self.account.leverage_long != self.config.leverage
                        or self.account.leverage_short != self.config.leverage
                    ):
                        raise RiskError("Leva configurata non confermata da Bybit")
                await self._fetch_prices()
                self.last_public = time.monotonic()
                new_session = self.grid is None
                if new_session:
                    self.session_id = uuid.uuid4().hex
                    self.grid = GridEngine(
                        self.price,
                        self.config.spacing_pct / D(100),
                        self.config.levels,
                        self.instrument.tick_size,
                        self.instrument.tick_size * self.config.hysteresis_ticks,
                        self.config.debounce_ms,
                    )
                else:
                    # Resume at current market without trading historical price jumps.
                    self.grid.on_price(self.price, self.exchange_time_ms())
                    self.grid.shift(self.price)
                await self.store.save_grid(self.grid.snapshot(), self.session_id)
                await self.store.put(
                    "configuration",
                    "app",
                    {"wizard_completed": self.wizard_completed, "session_id": self.session_id},
                )
                if new_session:
                    self.grid.on_price(self.price, self.exchange_time_ms())
                    await self.store.save_grid(self.grid.snapshot(), self.session_id)
                self.status = "RUNNING"
                self.error = None
                await self.manager.ensure_protection(self.active_recovery)
                if new_session and self.config.initial_pair:
                    await self._pair("initial", 0)
                await self.notify(
                    "started",
                    "Bot avviato",
                    {"environment": self.environment.value, "symbol": self.config.symbol},
                )
            except Exception as exc:
                await self.fail_safe(exc)
                raise

    async def _pair(self, level_id: str, sequence: int):
        if self.active_recovery:
            return
        from .grid import round_down

        pair = client_id(self.session_id, level_id, str(sequence))
        qty = round_down(self.config.order_size_usdt / self.price, self.instrument.qty_step)
        intents = [
            OrderIntent(
                environment=self.environment,
                symbol=self.config.symbol,
                order_link_id=client_id(pair, side.value),
                side=side,
                qty=qty,
                purpose="GRID",
                pair_id=pair,
                level_id=level_id,
                slippage_pct=self.config.slippage_pct,
            )
            for side in Side
        ]
        # Preflight both legs together before submitting the first. Exchange does not
        # offer atomic two-leg fills; any rejection halts rather than compensating blindly.
        ctx = await self.risk_context(intents[0])
        for intent in intents:
            self.manager.risk.validate_order(intent, ctx, self.config, self.instrument)
            ctx.reserved_notional += qty * self.price
        for intent in intents:
            await self.manager.submit(intent)

    async def pause(self):
        # Immediate state change precedes waiting for actor lock and REST cancellations.
        self.status = "PAUSED"
        async with self.lock:
            try:
                if self.manager:
                    await self.manager.pause_entries()
                await self.notify("paused", "Bot in pausa; posizioni mantenute", {})
            except Exception as exc:
                await self.fail_safe(exc)
                raise

    async def state(self):
        # The UI must observe one coherent actor snapshot, including fills and costs.
        async with self.lock:
            return await self._state()

    async def _state(self):
        try:
            positions = await self.store.lots()
            orders = await self.store.orders()
            return {
                "version": __version__,
                "environment": self.environment.value,
                "status": self.status,
                "connected": self.connected,
                "public_connected": self.public_connected,
                "private_connected": self.private_connected,
                "latency_ms": getattr(self.adapter, "latency_ms", None),
                "error": self.error,
                "account": self.account.model_dump(mode="json") if self.account else None,
                "price": str(self.price) if self.price is not None else None,
                "mark_price": str(self.mark_price) if self.mark_price is not None else None,
                "config": self.config.model_dump(mode="json"),
                "grid": [r.model_dump(mode="json") for r in self.grid.levels] if self.grid else [],
                "positions": positions,
                "orders": orders,
                "recovery": await self.recovery_plans(),
                "portfolio": await self.portfolio(positions),
                "candles": self.candles,
                "support_resistance": self.sr,
                "wizard_completed": self.wizard_completed,
                "mainnet_allowed": self.mainnet_allowed,
            }
        except Exception as exc:
            await self.fail_safe(exc)
            raise

    async def _monitor(self):
        counter = 0
        while not self.shutting_down:
            await asyncio.sleep(2)
            counter += 1
            if not self.adapter or not self.manager:
                continue
            async with self.lock:
                try:
                    if self.status == "RUNNING" and time.monotonic() - self.last_public > 15:
                        raise RiskError("Prezzo realtime scaduto; nuovi ordini sospesi")
                    if counter % 5 == 0:
                        was_running = self.status == "RUNNING"
                        await self._reconcile()
                        # Recovery after a reconnect requires explicit Start to resume entries.
                        if was_running:
                            self.status = "RUNNING"
                        elif (
                            self.status == "DEGRADED"
                            and self.public_connected
                            and self.private_connected
                        ):
                            self.status = "PAUSED"
                            self.error = None
                        if self.public_connected and self.private_connected:
                            await self._recovery_protection()
                            await self.manager.ensure_protection(self.active_recovery)
                    if counter % 15 == 0:
                        self.candles = await self.adapter.candles(
                            self.config.symbol, self.config.support_resistance_timeframe
                        )
                        self._analyze_sr()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self.fail_safe(exc)

    async def shutdown(self):
        self.shutting_down = True
        self.status = "PAUSED"
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await self.pause()
        finally:
            if self.ws:
                await self.ws.stop()
            if self.adapter:
                await self.adapter.close()
            if self.store:
                await self.store.close()
