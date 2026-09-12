"""Protocol fault fixtures and actual loopback HTTP/WebSocket integration."""

import asyncio
import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest
from gridbot.errors import DatabaseError
from gridbot.exchange import BybitDemoAdapter
from gridbot.models import Credentials, Environment, OrderIntent, Side
from gridbot.websocket import WebSocketManager
from mock_bybit import LoopbackTransport
from websockets.asyncio.client import connect

pytestmark = pytest.mark.asyncio


def credentials(key="LOCAL_WS_KEY", secret="LOCAL_WS_SECRET"):
    return Credentials(environment=Environment.DEMO, api_key=key, api_secret=secret)


async def wait_until(predicate, timeout=2.0):
    async def check():
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(check(), timeout=timeout)


class FixtureSocket:
    def __init__(
        self, *, auth_ok=True, subscribe_ok=True, events=None, before_subscribe_ack=False, pong=True
    ):
        self.auth_ok, self.subscribe_ok = auth_ok, subscribe_ok
        self.events = events or []
        self.before_subscribe_ack = before_subscribe_ack
        self.pong = pong
        self.received_auth_ack = False
        self.sent = []
        self.queue = asyncio.Queue()

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        if frame["op"] == "auth":
            key, expires, signature = frame["args"]
            assert key == "LOCAL_WS_KEY"
            assert (
                signature
                == hmac.new(
                    b"LOCAL_WS_SECRET", f"GET/realtime{expires}".encode(), hashlib.sha256
                ).hexdigest()
            )
            await self.queue.put({"op": "auth", "success": self.auth_ok})
        elif frame["op"] == "subscribe":
            if "order" in frame["args"]:
                assert self.received_auth_ack, "private subscribe must wait for auth ACK"
            if self.before_subscribe_ack:
                for event in self.events:
                    await self.queue.put(event)
            await self.queue.put({"op": "subscribe", "success": self.subscribe_ok})
            if not self.before_subscribe_ack:
                for event in self.events:
                    await self.queue.put(event)
        elif frame["op"] == "ping" and self.pong:
            await self.queue.put({"op": "pong"})

    async def recv(self):
        frame = await self.queue.get()
        if isinstance(frame, Exception):
            raise frame
        if frame.get("op") == "auth":
            self.received_auth_ack = True
        return json.dumps(frame)


class FixtureContext:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FixtureConnector:
    def __init__(self, factory):
        self.factory = factory
        self.sockets = {"public": [], "private": []}
        self.urls = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        source = "private" if url.endswith("private") else "public"
        socket = self.factory(source, len(self.sockets[source]))
        self.sockets[source].append(socket)
        return FixtureContext(socket)


async def test_private_authentication_precedes_subscription_and_status_waits_for_ack():
    chronology = []
    event = {"topic": "execution", "data": [{"execId": "early-fixture-execution"}]}
    connector = FixtureConnector(
        lambda source, count: FixtureSocket(
            events=[event] if source == "private" else [], before_subscribe_ack=True
        )
    )

    async def status(source, connected):
        chronology.append((source, connected))

    async def on_event(frame):
        assert ("private", True) in chronology
        chronology.append(("event", frame["data"][0]["execId"]))

    adapter = BybitDemoAdapter(
        credentials(), transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    manager = WebSocketManager(adapter, "BTCUSDT", on_event, status, connector=connector)
    try:
        await manager.start()
        await wait_until(lambda: any(item[0] == "event" for item in chronology))
        private = connector.sockets["private"][0]
        assert [frame["op"] for frame in private.sent] == ["auth", "subscribe"]
        assert private.sent[1]["args"] == ["order", "execution", "position", "wallet"]
        assert chronology.index(("private", True)) < chronology.index(
            ("event", "early-fixture-execution")
        )
        assert "wss://stream-demo.bybit.com/v5/private" in connector.urls
        assert "wss://stream.bybit.com/v5/public/linear" in connector.urls
    finally:
        await manager.stop()
        await adapter.close()
    assert not any(manager.connected.values())


async def test_invalid_private_auth_never_subscribes_and_never_claims_connected():
    statuses = []
    connector = FixtureConnector(lambda source, count: FixtureSocket(auth_ok=source != "private"))

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        return None

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(adapter, "BTCUSDT", on_event, status, connector=connector)
    try:
        await manager.start()
        await wait_until(lambda: manager._tasks[1].done())
        assert [frame["op"] for frame in connector.sockets["private"][0].sent] == ["auth"]
        assert ("private", True) not in statuses
        assert manager.reconnect_count["private"] == 0
        assert manager.last_error is not None
    finally:
        await manager.stop()
        await adapter.close()


async def test_disconnect_reconnect_reauthenticates_and_restores_all_subscriptions():
    connector = FixtureConnector(lambda source, count: FixtureSocket())
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        return None

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(
        adapter, "BTCUSDT", on_event, status, connector=connector, reconnect_delay=0.001
    )
    try:
        await manager.start()
        await wait_until(lambda: all(manager.connected.values()))
        await connector.sockets["private"][0].queue.put(ConnectionError("fixture connection loss"))
        await wait_until(
            lambda: len(connector.sockets["private"]) == 2 and manager.connected["private"]
        )
        second = connector.sockets["private"][1]
        assert [frame["op"] for frame in second.sent] == ["auth", "subscribe"]
        assert second.sent[1]["args"] == ["order", "execution", "position", "wallet"]
        assert statuses.count(("private", True)) == 2
        assert ("private", False) in statuses
    finally:
        await manager.stop()
        await adapter.close()


async def test_missing_heartbeat_pong_disconnects_before_more_events_are_accepted():
    connector = FixtureConnector(lambda source, count: FixtureSocket(pong=source != "private"))
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        return None

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(
        adapter,
        "BTCUSDT",
        on_event,
        status,
        connector=connector,
        heartbeat_interval=0.005,
        pong_timeout=0.005,
        reconnect_delay=0.05,
    )
    try:
        await manager.start()
        await wait_until(lambda: all(manager.connected.values()))
        await wait_until(lambda: ("private", False) in statuses)
        assert not manager.connected["private"]
        assert any(frame["op"] == "ping" for frame in connector.sockets["private"][0].sent)
    finally:
        await manager.stop()
        await adapter.close()


async def test_duplicate_and_out_of_order_execution_frames_are_preserved_for_transactional_processor():
    execution = {"topic": "execution", "data": [{"execId": "fixture-e1", "execQty": "4"}]}
    order = {
        "topic": "order",
        "data": [
            {
                "orderId": "fixture-order",
                "qty": "10",
                "cumExecQty": "4",
                "orderStatus": "PartiallyFilled",
            }
        ],
    }
    frames = [execution, execution, order]
    delivered = []
    connector = FixtureConnector(
        lambda source, count: FixtureSocket(events=frames if source == "private" else [])
    )

    async def status(source, connected):
        return None

    async def on_event(frame):
        delivered.append(frame)

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(adapter, "BTCUSDT", on_event, status, connector=connector)
    try:
        await manager.start()
        await wait_until(lambda: len(delivered) == 3)
        assert (
            delivered == frames
        )  # Database deduplicates execId, transport does not discard recovery evidence.
    finally:
        await manager.stop()
        await adapter.close()


async def test_persistence_callback_failure_disconnects_and_stops_reconnect_loop(caplog):
    connector = FixtureConnector(
        lambda source, count: FixtureSocket(
            events=[{"topic": "execution", "data": []}] if source == "private" else []
        )
    )
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        raise DatabaseError("LOCAL_WS_SECRET must not be logged")

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(adapter, "BTCUSDT", on_event, status, connector=connector)
    try:
        await manager.start()
        await wait_until(lambda: manager._tasks[1].done())
        assert not manager.connected["private"]
        assert ("private", False) in statuses
        assert manager.reconnect_count["private"] == 0
        assert "LOCAL_WS_SECRET" not in caplog.text
        assert "processing failed" in manager.last_error
    finally:
        await manager.stop()
        await adapter.close()


async def test_subscribe_rejection_never_reports_ready():
    connector = FixtureConnector(
        lambda source, count: FixtureSocket(subscribe_ok=source != "private")
    )
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        return None

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(
        adapter, "BTCUSDT", on_event, status, connector=connector, reconnect_delay=0.05
    )
    try:
        await manager.start()
        await wait_until(lambda: ("private", False) in statuses)
        assert ("private", True) not in statuses
    finally:
        await manager.stop()
        await adapter.close()


async def test_actual_loopback_rest_and_ws_authentication_execution_and_cancellation(
    local_bybit_server,
):
    server = local_bybit_server
    adapter = BybitDemoAdapter(
        credentials(server.state.api_key, server.state.api_secret),
        transport=LoopbackTransport(server),
    )
    statuses, events = [], []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        events.append(frame)

    def connector(url, **kwargs):
        path = "/v5/private" if url.endswith("private") else "/v5/public/linear"
        return connect(server.ws_url + path, **kwargs)

    manager = WebSocketManager(
        adapter,
        "BTCUSDT",
        on_event,
        status,
        connector=connector,
        heartbeat_interval=0.02,
        pong_timeout=0.05,
    )
    try:
        account = await adapter.account()
        assert account.uid == server.state.uid and account.hedge_mode and account.permissions
        await manager.start()
        await wait_until(lambda: all(manager.connected.values()))
        order = OrderIntent(
            environment=Environment.DEMO,
            symbol="BTCUSDT",
            order_link_id="loopback-real-protocol-1",
            side=Side.LONG,
            qty=Decimal("0.001"),
        )
        acknowledgement = await adapter.create_order(order)
        await wait_until(lambda: any(frame.get("topic") == "execution" for frame in events))
        fetched = await adapter.find_order("BTCUSDT", order.order_link_id)
        assert fetched["orderId"] == acknowledgement["orderId"]
        assert fetched["orderStatus"] == "Filled"
        executions = await adapter.executions("BTCUSDT")
        assert executions[0]["execQty"] == "0.001"
        assert any(frame["topic"] == "tickers.BTCUSDT" for frame in events)
        limit = order.model_copy(
            update={
                "order_link_id": "loopback-cancel-limit-1",
                "order_type": "Limit",
                "price": Decimal("60000"),
            }
        )
        pending = await adapter.create_order(limit)
        await adapter.cancel_order("BTCUSDT", pending["orderId"], limit.order_link_id)
        assert (await adapter.find_order("BTCUSDT", limit.order_link_id))[
            "orderStatus"
        ] == "Cancelled"
    finally:
        await manager.stop()
        await adapter.close()


async def test_actual_loopback_ws_reconnect_restores_subscription(local_bybit_server):
    server = local_bybit_server
    adapter = BybitDemoAdapter(
        credentials(server.state.api_key, server.state.api_secret),
        transport=LoopbackTransport(server),
    )
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        return None

    def connector(url, **kwargs):
        return connect(
            server.ws_url + ("/v5/private" if url.endswith("private") else "/v5/public/linear"),
            **kwargs,
        )

    manager = WebSocketManager(
        adapter, "BTCUSDT", on_event, status, connector=connector, reconnect_delay=0.001
    )
    try:
        await manager.start()
        await wait_until(lambda: all(manager.connected.values()))
        await server.state.disconnect_private()
        await wait_until(lambda: statuses.count(("private", True)) == 2)
        assert ("private", False) in statuses
        assert server.state.private_clients[0][1] == {"order", "execution", "position", "wallet"}
    finally:
        await manager.stop()
        await adapter.close()


@pytest.mark.parametrize("phase", ["event", "status"])
async def test_slow_callback_does_not_block_heartbeat_reader_or_cause_false_disconnect(phase):
    entered, released = asyncio.Event(), asyncio.Event()
    connector = FixtureConnector(
        lambda source, count: FixtureSocket(
            events=[{"topic": "execution", "data": []}] if source == "private" else []
        )
    )
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))
        if phase == "status" and source == "private" and connected:
            entered.set()
            await released.wait()

    async def on_event(frame):
        if phase == "event":
            entered.set()
            await released.wait()

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(
        adapter,
        "BTCUSDT",
        on_event,
        status,
        connector=connector,
        heartbeat_interval=0.005,
        pong_timeout=0.005,
        reconnect_delay=0.01,
    )
    try:
        await manager.start()
        await asyncio.wait_for(entered.wait(), timeout=1)
        await asyncio.sleep(0.05)  # Callback remains blocked for ten ping intervals.
        assert manager.connected["private"]
        assert ("private", False) not in statuses
        assert manager.reconnect_count["private"] == 0
        assert sum(frame["op"] == "ping" for frame in connector.sockets["private"][0].sent) >= 3
        released.set()
    finally:
        released.set()
        await manager.stop()
        await adapter.close()


async def test_bounded_queue_overflow_disconnects_and_requires_reconciliation():
    frames = [{"topic": "execution", "data": [{"execId": str(number)}]} for number in range(4)]
    connector = FixtureConnector(
        lambda source, count: FixtureSocket(events=frames if source == "private" else [])
    )
    statuses = []

    async def status(source, connected):
        statuses.append((source, connected))

    async def on_event(frame):
        return None

    adapter = BybitDemoAdapter(credentials())
    manager = WebSocketManager(
        adapter,
        "BTCUSDT",
        on_event,
        status,
        connector=connector,
        event_queue_size=1,
        reconnect_delay=0.1,
    )
    try:
        await manager.start()
        await wait_until(lambda: ("private", False) in statuses)
        assert not manager.connected["private"]
        assert manager.last_error is not None
    finally:
        await manager.stop()
        await adapter.close()
