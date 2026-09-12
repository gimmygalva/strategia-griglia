"""Credential identity, environment changes and reconciliation lifecycle."""

from __future__ import annotations

import asyncio
import time

from .errors import NetworkError, RiskError, ValidationError
from .models import AccountInfo, Credentials, Environment
from .orders import OrderManager
from .reconciliation import ReconciliationService

STARTUP_ACCOUNT_TIMEOUT_SECONDS = 20


class AccountConnectionMixin:
    async def restore_verified_account(self) -> None:
        """Read/reconcile a saved verified account; never authorize or start trading."""
        identity = await self.store.get("configuration", "account_identity")
        if not self.credentials_store.persistent or not identity:
            return
        try:
            # Bound startup so an unavailable exchange cannot hide the local UI.
            # The existing connect lock and UID checks apply to this path too.
            await asyncio.wait_for(
                self.connect(self.environment), timeout=STARTUP_ACCOUNT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            await self._disconnect()
            await self.fail_safe(NetworkError("Riconnessione account scaduta: strategia sospesa"))
        except Exception as exc:
            # connect() can fail before its own guarded adapter section, e.g.
            # inaccessible Keychain. All startup failures remain visible and paused.
            await self._disconnect()
            await self.fail_safe(exc)

    async def save_credentials(self, credentials: Credentials) -> None:
        async with self.lock:
            if self.status == "RUNNING":
                raise RiskError("Mettere in pausa prima di modificare le credenziali")
            # Old verified identity must be invalidated when secrets change.
            await self._disconnect()
            await asyncio.to_thread(self.credentials_store.save, credentials)
            await self.notify(
                "credentials_saved",
                "Credenziali salvate",
                {"environment": credentials.environment.value},
            )

    async def _disconnect(self) -> None:
        self.status = "DISCONNECTED"
        self.reconciled = False
        self.connected = self.public_connected = self.private_connected = False
        self.live_confirmed = False
        if self.ws:
            await self.ws.stop()
            self.ws = None
        if self.adapter:
            await self.adapter.close()
            self.adapter = None
        self.manager = None
        self.account = None
        self.price = None
        self.mark_price = None
        self.last_mark = 0.0
        self.candles = []
        self.exchange_positions = []
        self.last_market_timestamp = None

    async def connect(self, environment: Environment) -> AccountInfo:
        from .risk import RiskEngine

        async with self.lock:
            if self.status == "RUNNING":
                raise RiskError("Mettere in pausa prima di cambiare ambiente")
            await self._disconnect()
            if environment != self.environment:
                await self.store.close()
                self.environment = environment
                self.grid = None
                self.session_id = None
                await self._open_store()
                await self._write_pointer()
                await self.notify(
                    "environment_changed",
                    "Ambiente selezionato",
                    {"environment": environment.value},
                )
            credentials = await asyncio.to_thread(self.credentials_store.load, environment)
            if not credentials:
                raise ValidationError("Credenziali non configurate per questo ambiente")
            try:
                self.adapter = self.adapter_factory(
                    credentials, mainnet_allowed=self.mainnet_allowed, live_confirmed=False
                )
                self.instrument = await self.adapter.instrument(self.config.symbol)
                self.account = await self.adapter.account()
                identity = await self.store.get("configuration", "account_identity")
                if identity and (
                    identity.get("uid") != self.account.uid
                    or identity.get("environment") != environment.value
                ):
                    raise RiskError(
                        "UID diverso dal database: usare le credenziali del conto originale"
                    )
                if not identity:
                    await self.store.put(
                        "configuration",
                        "account_identity",
                        {"uid": self.account.uid, "environment": environment.value},
                    )
                await self._fetch_prices()
                self.candles = await self.adapter.candles(
                    self.config.symbol, self.config.support_resistance_timeframe
                )
                self._analyze_sr()
                self.connected = True
                self.manager = OrderManager(
                    self.adapter,
                    self.store,
                    RiskEngine(),
                    self.config,
                    self.instrument,
                    self.risk_context,
                    self.notify,
                    pre_send=self.validate_send,
                )
                self.status = "RECONCILING"
                await self._reconcile()
                self.status = "READY"
                self.error = None
                self.ws = self.websocket_factory(
                    self.adapter, self.config.symbol, self.on_event, self.on_status
                )
                await self.ws.start()
                await self.store.put(
                    "account_snapshots", str(time.time_ns()), self.account.model_dump(mode="json")
                )
                await self.notify(
                    "connected",
                    "Account Bybit verificato",
                    {"uid": self.account.uid, "environment": environment.value},
                )
                return self.account
            except Exception as exc:
                await self.fail_safe(exc)
                raise

    async def _reconcile(self) -> None:
        if not self.manager:
            raise RiskError("Account non connesso")
        self.reconciled = False
        service = ReconciliationService(self.adapter, self.store, self.manager, self.config.symbol)
        _, self.exchange_positions = await service.run()
        account = await self.adapter.account()
        if self.account and account.uid != self.account.uid:
            raise RiskError("UID account cambiato: trading bloccato")
        self.account = account
        await self._fetch_prices()
        await self._daily_baseline()
        self.reconciled = True
        await self.notify("reconciled", "Stato Bybit riconciliato", {})
