"""A LOCAL SIMULATOR used exclusively by automated tests.

This is an actual loopback HTTP/WebSocket server, not a production exchange adapter
and never an implementation of Bybit Demo Trading. It validates V5 request signing
and models exchange acknowledgement separately from execution confirmation.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import socket
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

D = Decimal


def utc_ms() -> int:
    return time.time_ns() // 1_000_000


def response(result: dict | None = None, code: int = 0, message: str = "OK") -> dict:
    return {
        "retCode": code,
        "retMsg": message,
        "result": result or {},
        "retExtInfo": {},
        "time": utc_ms(),
    }


@dataclass
class Fault:
    """One consumed fault; ``after`` faults occur after a mutation is accepted."""

    kind: str
    delay: float = 0.1
    after: bool = False


@dataclass
class MockBybitState:
    api_key: str = "local-simulator-key"
    api_secret: str = "local-simulator-secret"
    uid: str = "424242"
    price: Decimal = D("67000")
    midnight_mark: Decimal | None = D("67000")
    equity: Decimal = D("100000")
    available_balance: Decimal = D("100000")
    fee_rate: Decimal = D("0.0006")
    uta_status: int = 5
    permission: bool = True
    hedge: bool = True
    leverage: Decimal = D("1")
    market_auto_fill: bool = True
    fill_fraction: Decimal = D("1")
    fill_delay: float = 0
    execution_first: bool = True
    duplicate_executions: bool = False
    stale_order_after_fill: bool = False
    disconnect_private_on_subscribe: bool = False
    latency: float = 0
    page_size: int = 50
    reject_next_create: bool = False
    orders: dict[str, dict] = field(default_factory=dict)
    executions: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)
    position_book: dict[int, dict] = field(
        default_factory=lambda: {
            1: {"qty": D("0"), "average": D("0")},
            2: {"qty": D("0"), "average": D("0")},
        }
    )
    calls: list[dict] = field(default_factory=list)
    faults: dict[str, deque[Fault]] = field(default_factory=lambda: defaultdict(deque))
    private_clients: list[tuple[asyncio.Queue, set[str]]] = field(default_factory=list)
    public_clients: list[tuple[asyncio.Queue, set[str]]] = field(default_factory=list)
    tasks: set[asyncio.Task] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    order_sequence: int = 0
    execution_sequence: int = 0

    def inject_fault(
        self, path: str, kind: str, *, count: int = 1, delay: float = 0.1, after: bool = False
    ) -> None:
        """Kinds: 429, 5xx, api_rate_limit, rejection, latency, accepted_timeout.

        ``accepted_timeout`` is automatically after acceptance, modeling the dangerous
        case in which the exchange received the order but the caller lost its ACK.
        """
        for _ in range(count):
            self.faults[path].append(Fault(kind, delay, after or kind == "accepted_timeout"))

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def broadcast(self, topic: str, data: list[dict] | dict, *, public: bool = False) -> None:
        clients = self.public_clients if public else self.private_clients
        event = {"id": f"event-{utc_ms()}", "topic": topic, "creationTime": utc_ms(), "data": data}
        if public:
            event.update({"type": "snapshot", "ts": utc_ms()})
        for queue, subscriptions in tuple(clients):
            if topic in subscriptions:
                await queue.put(event)

    def positions(self) -> list[dict]:
        result = []
        for idx, book in self.position_book.items():
            pnl = book["qty"] * (self.price - book["average"]) * (1 if idx == 1 else -1)
            result.append(
                {
                    "symbol": "BTCUSDT",
                    "positionIdx": idx if self.hedge else 0,
                    "side": "Buy" if idx == 1 else "Sell",
                    "size": str(book["qty"]),
                    "avgPrice": str(book["average"]),
                    "entryPrice": str(book["average"]),
                    "positionValue": str(book["qty"] * self.price),
                    "markPrice": str(self.price),
                    "unrealisedPnl": str(pnl),
                    "cumRealisedPnl": "0",
                    "leverage": str(self.leverage),
                    "liqPrice": "",
                    "positionStatus": "Normal",
                    "updatedTime": str(utc_ms()),
                }
            )
        return result

    def wallet(self) -> dict:
        unrealized = sum((D(p["unrealisedPnl"]) for p in self.positions()), D(0))
        equity = self.equity + unrealized
        return {
            "accountType": "UNIFIED",
            "totalEquity": str(equity),
            "totalWalletBalance": str(self.equity),
            "totalAvailableBalance": str(self.available_balance),
            "totalPerpUPL": str(unrealized),
            "coin": [
                {
                    "coin": "USDT",
                    "equity": str(equity),
                    "walletBalance": str(self.equity),
                    "availableToWithdraw": str(self.available_balance),
                    "unrealisedPnl": str(unrealized),
                }
            ],
        }

    async def fill(
        self, order_id: str, qty: Decimal | None = None, price: Decimal | None = None
    ) -> dict | None:
        """Fill actual quantity once; remainder remains pending and keeps no imaginary PnL."""
        async with self.lock:
            order = self.orders[order_id]
            remaining = D(order["qty"]) - D(order["cumExecQty"])
            qty = min(remaining, qty if qty is not None else remaining)
            if qty <= 0 or order["orderStatus"] in {"Cancelled", "Rejected"}:
                return None
            price = price if price is not None else self.price
            previous_cum = D(order["cumExecQty"])
            idx = int(order["positionIdx"])
            book = self.position_book[idx]
            close_qty = D(0)
            realized = D(0)
            if order["reduceOnly"]:
                qty = min(qty, book["qty"])
                if qty <= 0:
                    return None
                close_qty = qty
                realized = qty * (price - book["average"]) * (1 if idx == 1 else -1)
                book["qty"] -= qty
                if book["qty"] == 0:
                    book["average"] = D(0)
            else:
                book["average"] = (book["average"] * book["qty"] + price * qty) / (
                    book["qty"] + qty
                )
                book["qty"] += qty
            fee = qty * price * self.fee_rate
            self.equity += realized - fee
            self.available_balance = self.equity - sum(
                (b["qty"] * self.price for b in self.position_book.values()), D(0)
            )
            cum = previous_cum + qty
            value = D(order["cumExecValue"]) + qty * price
            order.update(
                {
                    "cumExecQty": str(cum),
                    "cumExecValue": str(value),
                    "avgPrice": str(value / cum),
                    "cumExecFee": str(D(order["cumExecFee"]) + fee),
                    "leavesQty": str(D(order["qty"]) - cum),
                    "orderStatus": "Filled" if cum == D(order["qty"]) else "PartiallyFilled",
                    "updatedTime": str(utc_ms()),
                }
            )
            self.execution_sequence += 1
            execution = {
                "category": "linear",
                "symbol": "BTCUSDT",
                "execId": f"exec-{self.execution_sequence:08d}",
                "orderId": order_id,
                "orderLinkId": order["orderLinkId"],
                "side": order["side"],
                "positionIdx": idx,
                "execType": "Trade",
                "execQty": str(qty),
                "execPrice": str(price),
                "execValue": str(price * qty),
                "execFee": str(fee),
                "feeRate": str(self.fee_rate),
                "execTime": str(utc_ms()),
                "isMaker": False,
                "closedSize": str(close_qty),
                "execPnl": str(realized),
                "orderQty": order["qty"],
                "leavesQty": order["leavesQty"],
            }
            self.executions.append(execution)
            order_copy = dict(order)
        if self.execution_first:
            await self.broadcast("execution", [execution])
            await self.broadcast("order", [order_copy])
        else:
            await self.broadcast("order", [order_copy])
            await self.broadcast("execution", [execution])
        if self.duplicate_executions:
            await self.broadcast("execution", [dict(execution)])
        if self.stale_order_after_fill:
            stale = dict(
                order_copy,
                orderStatus="New",
                cumExecQty="0",
                cumExecValue="0",
                avgPrice="",
                leavesQty=order["qty"],
            )
            await self.broadcast("order", [stale])
        await self.broadcast("position", self.positions())
        await self.broadcast("wallet", [self.wallet()])
        return execution

    async def _delayed_fill(self, order_id: str) -> None:
        await asyncio.sleep(self.fill_delay)
        order = self.orders[order_id]
        await self.fill(order_id, D(order["qty"]) * self.fill_fraction)

    async def advance_market(self, price: Decimal, *, fill_limits: bool = True) -> None:
        self.price = price
        await self.broadcast(
            "tickers.BTCUSDT",
            {"symbol": "BTCUSDT", "lastPrice": str(price), "markPrice": str(price)},
            public=True,
        )
        if fill_limits:
            for order_id, order in list(self.orders.items()):
                if order["orderType"] != "Limit" or order["orderStatus"] not in {
                    "New",
                    "PartiallyFilled",
                }:
                    continue
                if (order["side"] == "Buy" and price <= D(order["price"])) or (
                    order["side"] == "Sell" and price >= D(order["price"])
                ):
                    await self.fill(order_id, price=D(order["price"]))

    async def settle_funding(self, side: str, amount: Decimal) -> dict:
        """Append a signed settlement movement; positive received, negative paid."""
        transaction = {
            "id": f"funding-{len(self.transactions) + 1:08d}",
            "transactionTime": str(utc_ms()),
            "symbol": "BTCUSDT",
            "category": "linear",
            "currency": "USDT",
            "side": side,
            "type": "SETTLEMENT",
            "funding": str(amount),
            "fee": "0",
            "cashFlow": "0",
            "change": str(amount),
        }
        self.transactions.append(transaction)
        self.equity += amount
        self.available_balance += amount
        await self.broadcast("wallet", [self.wallet()])
        return transaction

    async def disconnect_private(self) -> None:
        for queue, _ in tuple(self.private_clients):
            await queue.put({"_disconnect": True})

    async def close(self) -> None:
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)


def create_app(state: MockBybitState) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def middleware(request: Request, call_next):
        body = await request.body()
        path = request.url.path
        state.calls.append(
            {
                "method": request.method,
                "path": path,
                "query": dict(request.query_params),
                "body": json.loads(body) if body else None,
            }
        )
        if not path.startswith("/v5/market/"):
            key = request.headers.get("X-BAPI-API-KEY", "")
            timestamp = request.headers.get("X-BAPI-TIMESTAMP", "")
            recv = request.headers.get("X-BAPI-RECV-WINDOW", "5000")
            if key != state.api_key:
                return JSONResponse(response(code=10003, message="API key is invalid"))
            try:
                if not utc_ms() - int(recv) <= int(timestamp) < utc_ms() + 1000:
                    return JSONResponse(response(code=10002, message="request expired"))
            except ValueError:
                return JSONResponse(response(code=10002, message="invalid timestamp"))
            material = request.url.query if request.method == "GET" else body.decode()
            expected = hmac.new(
                state.api_secret.encode(),
                f"{timestamp}{key}{recv}{material}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(request.headers.get("X-BAPI-SIGN", ""), expected):
                return JSONResponse(response(code=10004, message="signature error"))
        fault = state.faults[path].popleft() if state.faults[path] else None
        if state.latency:
            await asyncio.sleep(state.latency)
        if fault and not fault.after:
            immediate = await apply_fault(fault)
            if immediate is not None:
                return immediate
        result = await call_next(request)
        if fault and fault.after:
            override = await apply_fault(fault)
            if override is not None:
                return override
        result.headers["X-Bapi-Limit"] = "10"
        result.headers["X-Bapi-Limit-Status"] = "9"
        result.headers["X-Bapi-Limit-Reset-Timestamp"] = str(utc_ms())
        return result

    async def apply_fault(fault: Fault):
        if fault.kind in {"latency", "accepted_timeout"}:
            await asyncio.sleep(fault.delay)
            return None
        if fault.kind == "429":
            return JSONResponse(
                response(code=10006, message="Too many visits"),
                status_code=429,
                headers={
                    "Retry-After": "0.01",
                    "X-Bapi-Limit-Status": "0",
                    "X-Bapi-Limit-Reset-Timestamp": str(utc_ms() + 10),
                },
            )
        if fault.kind == "5xx":
            return JSONResponse(response(code=10016, message="server error"), status_code=503)
        if fault.kind == "api_rate_limit":
            return JSONResponse(
                response(code=10006, message="Too many visits"),
                headers={"X-Bapi-Limit-Status": "0"},
            )
        if fault.kind == "rejection":
            return JSONResponse(response(code=110007, message="available balance insufficient"))
        raise ValueError(f"Unknown LOCAL SIMULATOR fault: {fault.kind}")

    def page(items: list[dict], request: Request) -> dict:
        start = int(request.query_params.get("cursor") or 0)
        limit = min(int(request.query_params.get("limit", state.page_size)), state.page_size)
        sliced = items[start : start + limit]
        cursor = str(start + limit) if start + limit < len(items) else ""
        return {"category": "linear", "list": sliced, "nextPageCursor": cursor}

    def filtered_orders(request: Request, *, open_only: bool) -> list[dict]:
        orders = list(state.orders.values())
        if open_only:
            orders = [
                o for o in orders if o["orderStatus"] in {"New", "PartiallyFilled", "Untriggered"}
            ]
        for key in ["symbol", "orderId", "orderLinkId"]:
            value = request.query_params.get(key)
            if value:
                orders = [o for o in orders if o[key] == value]
        return [dict(o) for o in orders]

    @app.get("/v5/market/time")
    async def server_time():
        return response({"timeSecond": str(int(time.time())), "timeNano": str(time.time_ns())})

    @app.get("/v5/market/instruments-info")
    async def instrument(request: Request):
        return response(
            {
                "category": "linear",
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "Trading",
                        "contractType": "LinearPerpetual",
                        "settleCoin": "USDT",
                        "quoteCoin": "USDT",
                        "baseCoin": "BTC",
                        "unifiedMarginTrade": True,
                        "priceFilter": {"tickSize": "0.1", "minPrice": "0.1", "maxPrice": "999999"},
                        "lotSizeFilter": {
                            "qtyStep": "0.001",
                            "minOrderQty": "0.001",
                            "maxOrderQty": "100",
                            "maxMktOrderQty": "10",
                            "minNotionalValue": "5",
                        },
                        "leverageFilter": {
                            "minLeverage": "1",
                            "maxLeverage": "100",
                            "leverageStep": "0.01",
                        },
                    }
                ],
                "nextPageCursor": "",
            }
        )

    @app.get("/v5/market/tickers")
    async def tickers():
        return response(
            {
                "category": "linear",
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "lastPrice": str(state.price),
                        "markPrice": str(state.price),
                        "bid1Price": str(state.price - D("0.1")),
                        "ask1Price": str(state.price + D("0.1")),
                    }
                ],
            }
        )

    @app.get("/v5/market/kline")
    async def candles(request: Request):
        interval = request.query_params.get("interval", "15")
        duration = 86400 if interval == "D" else int(interval) * 60
        end = int(time.time()) // duration * duration
        limit = min(int(request.query_params.get("limit", 200)), 1000)
        data = [
            [
                str((end - i * duration) * 1000),
                str(state.price - D(10)),
                str(state.price + D(20)),
                str(state.price - D(20)),
                str(state.price),
                "10",
                str(state.price * 10),
            ]
            for i in range(limit)
        ]
        return response({"symbol": "BTCUSDT", "category": "linear", "list": data})

    @app.get("/v5/market/mark-price-kline")
    async def mark_price_candles(request: Request):
        start = int(request.query_params.get("start", utc_ms() // 86400000 * 86400000))
        end = int(request.query_params.get("end", start + 59999))
        timestamp = start // 60000 * 60000
        rows = []
        if state.midnight_mark is not None and timestamp <= end:
            rows = [
                [
                    str(timestamp),
                    str(state.midnight_mark),
                    str(state.midnight_mark),
                    str(state.midnight_mark),
                    str(state.midnight_mark),
                ]
            ]
        return response({"symbol": "BTCUSDT", "category": "linear", "list": rows})

    @app.get("/v5/user/query-api")
    async def query_api():
        return response(
            {
                "userID": int(state.uid),
                "parentUid": "0",
                "isMaster": True,
                "readOnly": 0 if state.permission else 1,
                "permissions": {"ContractTrade": ["Order", "Position"] if state.permission else []},
                "unified": 1,
                "uta": 1,
                "type": 1,
                "ips": ["*"],
            }
        )

    @app.get("/v5/account/info")
    async def account_info():
        return response(
            {
                "unifiedMarginStatus": state.uta_status,
                "marginMode": "REGULAR_MARGIN",
                "isMasterTrader": False,
            }
        )

    @app.get("/v5/account/wallet-balance")
    async def wallet():
        return response({"list": [state.wallet()]})

    @app.get("/v5/account/fee-rate")
    async def fee():
        return response(
            {
                "category": "linear",
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "takerFeeRate": str(state.fee_rate),
                        "makerFeeRate": str(state.fee_rate),
                    }
                ],
            }
        )

    @app.get("/v5/account/transaction-log")
    async def transactions(request: Request):
        data = list(state.transactions)
        if request.query_params.get("startTime"):
            data = [
                t
                for t in data
                if int(t["transactionTime"]) >= int(request.query_params["startTime"])
            ]
        if request.query_params.get("endTime"):
            data = [
                t for t in data if int(t["transactionTime"]) <= int(request.query_params["endTime"])
            ]
        return response(page(data, request))

    @app.get("/v5/position/list")
    async def positions():
        return response({"category": "linear", "list": state.positions(), "nextPageCursor": ""})

    @app.post("/v5/position/set-leverage")
    async def leverage(request: Request):
        body = await request.json()
        state.leverage = D(body["buyLeverage"])
        return response()

    @app.get("/v5/order/realtime")
    async def realtime(request: Request):
        return response(
            page(
                filtered_orders(
                    request, open_only=request.query_params.get("openOnly", "0") == "0"
                ),
                request,
            )
        )

    @app.get("/v5/order/history")
    async def history(request: Request):
        return response(page(filtered_orders(request, open_only=False), request))

    @app.get("/v5/execution/list")
    async def executions(request: Request):
        data = list(state.executions)
        if request.query_params.get("startTime"):
            data = [e for e in data if int(e["execTime"]) >= int(request.query_params["startTime"])]
        for key in ["symbol", "orderId", "orderLinkId"]:
            if request.query_params.get(key):
                data = [e for e in data if e[key] == request.query_params[key]]
        return response(page(data, request))

    @app.post("/v5/order/create")
    async def create(request: Request):
        payload = await request.json()
        if state.reject_next_create:
            state.reject_next_create = False
            return response(code=110007, message="available balance insufficient")
        idx = int(payload.get("positionIdx", 0))
        if idx not in {1, 2} or not state.hedge:
            return response(code=10001, message="position idx not match position mode")
        expected_side = (
            ("Sell" if idx == 1 else "Buy")
            if payload.get("reduceOnly")
            else ("Buy" if idx == 1 else "Sell")
        )
        if payload.get("side") != expected_side:
            return response(code=10001, message="positionIdx and side mismatch")
        qty = D(payload.get("qty", "0"))
        if qty <= 0 or qty % D("0.001") != 0:
            return response(code=10001, message="invalid qty")
        link = payload.get("orderLinkId", "")
        async with state.lock:
            if any(o["orderLinkId"] == link for o in state.orders.values()):
                return response(code=110072, message="OrderLinkedID is duplicate")
            state.order_sequence += 1
            order_id = f"local-order-{state.order_sequence:08d}"
            order = {
                "category": "linear",
                "symbol": payload["symbol"],
                "orderId": order_id,
                "orderLinkId": link,
                "side": payload["side"],
                "positionIdx": idx,
                "orderType": payload.get("orderType", "Market"),
                "qty": str(qty),
                "price": str(payload.get("price", "0")),
                "avgPrice": "",
                "cumExecQty": "0",
                "cumExecValue": "0",
                "cumExecFee": "0",
                "leavesQty": str(qty),
                "orderStatus": "New",
                "reduceOnly": bool(payload.get("reduceOnly", False)),
                "createdTime": str(utc_ms()),
                "updatedTime": str(utc_ms()),
            }
            state.orders[order_id] = order
        await state.broadcast("order", [dict(order)])
        if order["orderType"] == "Market" and state.market_auto_fill:
            if state.fill_delay:
                state.spawn(state._delayed_fill(order_id))
            else:
                await state.fill(order_id, qty * state.fill_fraction)
        return response({"orderId": order_id, "orderLinkId": link})

    @app.post("/v5/order/cancel")
    async def cancel(request: Request):
        payload = await request.json()
        order = state.orders.get(payload.get("orderId", ""))
        if order is None and payload.get("orderLinkId"):
            order = next(
                (o for o in state.orders.values() if o["orderLinkId"] == payload["orderLinkId"]),
                None,
            )
        if order is None:
            return response(code=110001, message="Order does not exist")
        if order["orderStatus"] in {"Filled", "Cancelled", "Rejected"}:
            return response(code=110001, message="Order does not exist")
        order["orderStatus"] = "Cancelled"
        order["updatedTime"] = str(utc_ms())
        await state.broadcast("order", [dict(order)])
        return response({"orderId": order["orderId"], "orderLinkId": order["orderLinkId"]})

    async def websocket_endpoint(websocket: WebSocket, *, private: bool):
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue()
        subscriptions: set[str] = set()
        clients = state.private_clients if private else state.public_clients
        clients.append((queue, subscriptions))
        authenticated = not private

        async def sender():
            while True:
                item = await queue.get()
                if item.get("_disconnect"):
                    await websocket.close(
                        code=1012, reason="LOCAL SIMULATOR injected disconnection"
                    )
                    return
                await websocket.send_json(item)

        sender_task = asyncio.create_task(sender())
        try:
            while True:
                message = await websocket.receive_json()
                op = message.get("op")
                req_id = message.get("req_id", "")
                if op == "auth":
                    args = message.get("args", [])
                    authenticated = False
                    if len(args) == 3:
                        key, expires, signature = args
                        expected = hmac.new(
                            state.api_secret.encode(),
                            f"GET/realtime{expires}".encode(),
                            hashlib.sha256,
                        ).hexdigest()
                        authenticated = (
                            key == state.api_key
                            and int(expires) > utc_ms()
                            and hmac.compare_digest(signature, expected)
                        )
                    await queue.put(
                        {
                            "op": "auth",
                            "success": authenticated,
                            "ret_msg": "" if authenticated else "invalid signature",
                            "conn_id": "local-simulator",
                            "req_id": req_id,
                        }
                    )
                elif op == "subscribe":
                    if not authenticated:
                        await queue.put(
                            {
                                "op": "subscribe",
                                "success": False,
                                "ret_msg": "authentication required",
                                "req_id": req_id,
                            }
                        )
                        continue
                    subscriptions.update(message.get("args", []))
                    await queue.put(
                        {
                            "op": "subscribe",
                            "success": True,
                            "ret_msg": "",
                            "conn_id": "local-simulator",
                            "req_id": req_id,
                        }
                    )
                    if private and state.disconnect_private_on_subscribe:
                        await queue.put({"_disconnect": True})
                    if not private and "tickers.BTCUSDT" in subscriptions:
                        await queue.put(
                            {
                                "topic": "tickers.BTCUSDT",
                                "type": "snapshot",
                                "ts": utc_ms(),
                                "data": {
                                    "symbol": "BTCUSDT",
                                    "lastPrice": str(state.price),
                                    "markPrice": str(state.price),
                                },
                            }
                        )
                elif op == "ping":
                    await queue.put(
                        {"op": "pong", "success": True, "ret_msg": "pong", "req_id": req_id}
                    )
        except (WebSocketDisconnect, RuntimeError):
            pass  # Expected transport shutdown is scoped to this test-only server.
        finally:
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task
            clients.remove((queue, subscriptions))

    @app.websocket("/v5/private")
    async def private_ws(websocket: WebSocket):
        await websocket_endpoint(websocket, private=True)

    @app.websocket("/v5/public/linear")
    async def public_ws(websocket: WebSocket):
        await websocket_endpoint(websocket, private=False)

    return app


@dataclass
class LocalBybitServer:
    """Started on an ephemeral loopback port; caller must await stop()."""

    state: MockBybitState = field(default_factory=MockBybitState)
    base_url: str = ""
    ws_url: str = ""
    server: uvicorn.Server | None = None
    task: asyncio.Task | None = None
    sock: socket.socket | None = None

    async def start(self) -> "LocalBybitServer":
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(128)
        port = self.sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.ws_url = f"ws://127.0.0.1:{port}"
        config = uvicorn.Config(
            create_app(self.state), log_level="error", lifespan="off", ws="websockets-sansio"
        )
        self.server = uvicorn.Server(config)
        self.task = asyncio.create_task(self.server.serve(sockets=[self.sock]))
        for _ in range(500):
            if self.server.started:
                return self
            if self.task.done():
                await self.task
                raise RuntimeError("LOCAL SIMULATOR server did not start")
            await asyncio.sleep(0.002)
        raise TimeoutError("LOCAL SIMULATOR loopback startup timeout")

    async def stop(self) -> None:
        await self.state.close()
        if self.server:
            self.server.should_exit = True
        if self.task:
            await asyncio.wait_for(self.task, timeout=5)
        if self.sock:
            self.sock.close()


class LoopbackTransport(httpx.AsyncBaseTransport):
    """HTTPX transport bridge only for tests; production endpoints stay immutable.

    Delegates actual HTTP bytes to the running loopback server, retaining request
    signing and timeout semantics. Original requested URLs are recorded separately
    so tests can prove DEMO and LIVE routing remain distinct.
    """

    def __init__(self, server: LocalBybitServer):
        self.server = server
        self.transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
        self.requested_urls: list[str] = []

    async def handle_async_request(self, request):
        self.requested_urls.append(str(request.url))
        target = httpx.URL(self.server.base_url).copy_with(
            path=request.url.path, query=request.url.query
        )
        forwarded = httpx.Request(
            request.method,
            target,
            headers=request.headers,
            content=await request.aread(),
            extensions=request.extensions,
        )
        return await self.transport.handle_async_request(forwarded)

    async def aclose(self):
        await self.transport.aclose()
