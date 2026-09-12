"""Bybit V5 public/private streams; connection is true only after ACK."""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import connect

from gridbot.errors import AuthenticationError, NetworkError, ValidationError
from gridbot.exchange import BybitAdapter

logger = logging.getLogger(__name__)


class CallbackError(NetworkError):
    code = "WEBSOCKET_CALLBACK_ERROR"


class WebSocketManager:
    def __init__(
        self,
        adapter: BybitAdapter,
        symbol: str,
        on_event: Callable[[dict], Awaitable[None]],
        on_status: Callable[[str, bool], Awaitable[None]],
        *,
        connector: Callable[..., Any] = connect,
        heartbeat_interval: float = 20.0,
        pong_timeout: float = 10.0,
        handshake_timeout: float = 10.0,
        reconnect_delay: float = 0.5,
        event_queue_size: int = 1024,
    ) -> None:
        if (
            not 1 <= event_queue_size <= 16384
            or min(heartbeat_interval, pong_timeout, handshake_timeout, reconnect_delay) <= 0
        ):
            raise ValidationError("Parametri WebSocket non validi")
        self.adapter = adapter
        self.symbol = symbol
        self.on_event = on_event
        self.on_status = on_status
        self._connector = connector
        self.heartbeat_interval = heartbeat_interval
        self.pong_timeout = pong_timeout
        self.handshake_timeout = handshake_timeout
        self.reconnect_delay = reconnect_delay
        self.event_queue_size = event_queue_size
        self.connected = {"public": False, "private": False}
        self.reconnect_count = {"public": 0, "private": 0}
        self.last_error: str | None = None
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._pending_funding_frames: set[int] = set()

    @property
    def pending_funding(self) -> int:
        """Settlements received by the reader but not yet handled by the actor."""
        return len(self._pending_funding_frames)

    async def start(self) -> None:
        if self._tasks:
            return
        self.adapter._validate()
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._runner("public"), name="bybit-public-stream"),
            asyncio.create_task(self._runner("private"), name="bybit-private-stream"),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for source in ("public", "private"):
            if self.connected[source]:
                await self._status(source, False)

    async def _status(self, source: str, connected: bool) -> None:
        self.connected[source] = connected
        if source == "private" and not connected:
            self._pending_funding_frames.clear()
        try:
            await self.on_status(source, connected)
        except Exception as exc:
            self.connected["public"] = False
            self.connected["private"] = False
            self.last_error = "WebSocket status callback failed; trading must remain paused"
            # Log only the exception class, never server messages or credentials.
            logger.error("websocket_status_callback_failed exception=%s", type(exc).__name__)
            raise CallbackError(self.last_error) from exc

    async def _dispatch(self, event: dict) -> None:
        try:
            await self.on_event(event)
        except Exception as exc:
            self.last_error = "WebSocket event processing failed; reconciliation required"
            logger.error("websocket_event_callback_failed exception=%s", type(exc).__name__)
            raise CallbackError(self.last_error) from exc

    @staticmethod
    def _decode(raw: Any) -> dict:
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError("invalid frame")
            return decoded
        except (ValueError, TypeError) as exc:
            raise NetworkError("WebSocket Bybit: frame non valido") from exc

    async def _handshake_ack(self, socket: Any, operation: str, pending: list[dict]) -> None:
        deadline = asyncio.get_running_loop().time() + self.handshake_timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise NetworkError("WebSocket Bybit: conferma handshake non ricevuta")
            try:
                frame = self._decode(await asyncio.wait_for(socket.recv(), timeout=remaining))
            except asyncio.TimeoutError as exc:
                raise NetworkError("WebSocket Bybit: handshake timeout") from exc
            if frame.get("op") == operation:
                if frame.get("success") is not True:
                    if operation == "auth":
                        raise AuthenticationError("Autenticazione WebSocket Bybit fallita")
                    raise NetworkError("Sottoscrizione WebSocket Bybit rifiutata")
                return
            if frame.get("topic"):
                # A fast execution can arrive immediately after subscription.
                pending.append(frame)
                if len(pending) > 1000:
                    raise NetworkError("WebSocket Bybit: buffer handshake oltre limite")

    async def _session(self, source: str, socket: Any) -> None:
        pending: list[dict] = []
        if source == "private":
            key = self.adapter.credentials.api_key.get_secret_value()
            secret = self.adapter.credentials.api_secret.get_secret_value()
            if not key.strip() or not secret.strip():
                raise AuthenticationError("Credenziali WebSocket Bybit mancanti")
            expires = int(time.time() * 1000) + self.adapter.clock_offset_ms + 10000
            signature = hmac.new(
                secret.encode(), f"GET/realtime{expires}".encode(), hashlib.sha256
            ).hexdigest()
            await socket.send(json.dumps({"op": "auth", "args": [key, expires, signature]}))
            await self._handshake_ack(socket, "auth", pending)
            topics = ["order", "execution", "position", "wallet"]
        else:
            topics = [f"tickers.{self.symbol}"]
        await socket.send(json.dumps({"op": "subscribe", "args": topics}))
        await self._handshake_ack(socket, "subscribe", pending)
        pong = asyncio.Event()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self.event_queue_size)
        for event in pending:
            self._enqueue(source, queue, event)
        reader = asyncio.create_task(
            self._reader(source, socket, pong, queue), name=f"bybit-{source}-reader"
        )
        heartbeat = asyncio.create_task(
            self._heartbeat(socket, pong), name=f"bybit-{source}-heartbeat"
        )
        dispatcher = asyncio.create_task(
            self._dispatcher(source, queue), name=f"bybit-{source}-dispatcher"
        )
        try:
            completed, _ = await asyncio.wait(
                (reader, heartbeat, dispatcher), return_when=asyncio.FIRST_COMPLETED
            )
            for task in completed:
                await task
        finally:
            for task in (reader, heartbeat, dispatcher):
                task.cancel()
            await asyncio.gather(reader, heartbeat, dispatcher, return_exceptions=True)

    def _enqueue(self, source: str, queue: asyncio.Queue[dict], frame: dict) -> None:
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull as exc:
            raise NetworkError("WebSocket event queue overflow: reconciliation required") from exc
        if (
            source == "private"
            and str(frame.get("topic", "")).startswith("execution")
            and isinstance(frame.get("data"), list)
            and any(
                isinstance(item, dict) and item.get("execType") == "Funding"
                for item in frame["data"]
            )
        ):
            # This synchronous marker precedes actor/DB waits without blocking pongs.
            self._pending_funding_frames.add(id(frame))

    async def _reader(
        self, source: str, socket: Any, pong: asyncio.Event, queue: asyncio.Queue[dict]
    ) -> None:
        while not self._stopping.is_set():
            frame = self._decode(await socket.recv())
            if frame.get("op") in {"pong", "ping"}:
                if frame.get("success") is False:
                    raise NetworkError("WebSocket Bybit: heartbeat rifiutato")
                pong.set()
                continue
            if frame.get("op") in {"auth", "subscribe"}:
                if frame.get("success") is not True:
                    raise NetworkError("WebSocket Bybit: connessione invalidata")
                continue
            if frame.get("topic"):
                self._enqueue(source, queue, frame)

    async def _dispatcher(self, source: str, queue: asyncio.Queue[dict]) -> None:
        # The reader must keep handling pongs while callbacks await REST/DB work.
        await self._status(source, True)
        while not self._stopping.is_set():
            event = await queue.get()
            try:
                await self._dispatch(event)
                self._pending_funding_frames.discard(id(event))
            finally:
                queue.task_done()

    async def _heartbeat(self, socket: Any, pong: asyncio.Event) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(self.heartbeat_interval)
            pong.clear()
            await socket.send(json.dumps({"op": "ping"}))
            try:
                await asyncio.wait_for(pong.wait(), timeout=self.pong_timeout)
            except asyncio.TimeoutError as exc:
                raise NetworkError("WebSocket Bybit: heartbeat timeout") from exc

    async def _runner(self, source: str) -> None:
        failures = 0
        while not self._stopping.is_set():
            fatal = False
            try:
                self.adapter._validate()
                url = (
                    self.adapter.endpoints.public_ws
                    if source == "public"
                    else self.adapter.endpoints.private_ws
                )
                async with self._connector(
                    url,
                    open_timeout=self.handshake_timeout,
                    close_timeout=5,
                    max_size=2**20,
                    max_queue=64,
                    ping_interval=None,
                    proxy=None,
                ) as socket:
                    await self._session(source, socket)
                failures = 0
            except asyncio.CancelledError:
                raise
            except AuthenticationError:
                self.last_error = "Autenticazione WebSocket Bybit fallita"
                fatal = True
            except ValidationError:
                self.last_error = "Ambiente WebSocket Bybit incoerente: trading bloccato"
                fatal = True
            except CallbackError:
                # Retry would mask broken persistence/event processing.
                fatal = True
            except Exception as exc:
                self.last_error = "WebSocket Bybit disconnesso: riconciliare prima di riprendere"
                logger.warning(
                    "websocket_disconnected source=%s exception=%s", source, type(exc).__name__
                )
                failures += 1
            finally:
                try:
                    await self._status(source, False)
                except CallbackError:
                    fatal = True
            if fatal or self._stopping.is_set():
                return
            self.reconnect_count[source] += 1
            delay = min(30.0, self.reconnect_delay * 2 ** min(failures, 6))
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue
