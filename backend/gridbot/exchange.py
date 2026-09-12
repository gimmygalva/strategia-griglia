"""Real Bybit V5 REST transport with conservative mutation semantics."""

import asyncio
import hashlib
import hmac
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from gridbot.environments import Endpoints, EnvironmentValidation, endpoints_for
from gridbot.errors import (
    AuthenticationError,
    BybitAPIError,
    NetworkError,
    OrderNotSentError,
    RiskError,
    UncertainOrderError,
    ValidationError,
)
from gridbot.models import AccountInfo, Credentials, Environment, Instrument, OrderIntent
from gridbot.tls import verified_context


class PermissionMissingError(BybitAPIError):
    code = "PERMISSION_MISSING"


class AccountTypeError(ValidationError):
    code = "ACCOUNT_TYPE_ERROR"


class HedgeModeError(ValidationError):
    code = "HEDGE_MODE_ERROR"


class ExchangeAdapter(Protocol):
    environment: Environment
    endpoints: Endpoints

    def set_order_guard(self, guard: Callable[[OrderIntent], None] | None) -> None: ...

    async def public_get(self, path: str, params: dict) -> dict: ...
    async def private_get(self, path: str, params: dict) -> dict: ...
    async def private_post(self, path: str, payload: dict) -> dict: ...
    async def instrument(self, symbol: str) -> Instrument: ...
    async def ticker(self, symbol: str) -> Decimal: ...
    async def midnight_mark(self, symbol: str, day_start_ms: int) -> Decimal: ...
    async def candles(self, symbol: str, interval: str = "15", limit: int = 200) -> list[dict]: ...
    async def account(self) -> AccountInfo: ...
    async def open_orders(self, symbol: str) -> list[dict]: ...
    async def positions(self, symbol: str) -> list[dict]: ...
    async def executions(self, symbol: str, start_time: int | None = None) -> list[dict]: ...
    async def transactions(self, symbol: str, start_time: int | None = None) -> list[dict]: ...
    async def find_order(self, symbol: str, order_link_id: str) -> dict | None: ...
    async def create_order(self, intent: OrderIntent) -> dict: ...
    async def cancel_order(self, symbol: str, order_id: str, order_link_id: str) -> dict: ...
    async def set_leverage(self, symbol: str, leverage: Decimal) -> None: ...
    async def close(self) -> None: ...


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"Dato Bybit non valido: {field}") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValidationError(f"Dato Bybit non valido: {field}")
    return result


def _wire(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValidationError("Valore numerico non finito")
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def _history_windows(start_time: int, now: int, tail_span_ms: int) -> list[tuple[int, int | None]]:
    """Keep historical bounds exact and leave the current tail to exchange time.

    Explicit bounds allow seven days for both endpoints. An omitted endTime
    implies seven days for executions but only 24 hours for transaction logs.
    Each caller reserves a shorter recent tail, so its server-implied interval
    includes current events despite a slightly negative synchronized clock.
    """
    tail_start = max(start_time, now - tail_span_ms)
    windows: list[tuple[int, int | None]] = []
    cursor_time = start_time
    while cursor_time < tail_start:
        end = min(cursor_time + 7 * 86400000 - 1, tail_start - 1)
        windows.append((cursor_time, end))
        cursor_time = end + 1
    windows.append((tail_start, None))
    return windows


class BybitAdapter:
    category = "linear"
    receive_window = 5000

    def __init__(
        self,
        credentials: Credentials,
        *,
        mainnet_allowed: bool = False,
        live_confirmed: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.credentials = credentials.model_copy(deep=True)
        self.environment = credentials.environment
        self.endpoints = endpoints_for(self.environment)
        EnvironmentValidation.validate(self.environment, self.credentials, self.endpoints)
        self.mainnet_allowed = mainnet_allowed
        self.live_confirmed = live_confirmed
        self.latency_ms: float | None = None
        self.clock_offset_ms = 0
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(4)
        self._order_guard: Callable[[OrderIntent], None] | None = None
        self._client = httpx.AsyncClient(
            transport=transport,
            verify=verified_context(),
            timeout=httpx.Timeout(15, connect=5, read=10),
            follow_redirects=False,
            trust_env=False,
        )

    def set_live_authorization(self, allowed: bool, confirmed: bool) -> None:
        self.mainnet_allowed = allowed
        self.live_confirmed = confirmed

    def set_order_guard(self, guard: Callable[[OrderIntent], None] | None) -> None:
        """Install the runtime's synchronous safety check at the send boundary."""
        self._order_guard = guard

    def _validate(self, *, mutation: bool = False) -> None:
        EnvironmentValidation.validate(self.environment, self.credentials, self.endpoints)
        if mutation and self.environment == Environment.MAINNET:
            if not self.mainnet_allowed or not self.live_confirmed:
                raise RiskError("LIVE bloccato: safety flag e conferma richiesti")

    def _headers(self, wire: str) -> dict[str, str]:
        key = self.credentials.api_key.get_secret_value()
        secret = self.credentials.api_secret.get_secret_value()
        if not key.strip() or not secret.strip():
            raise AuthenticationError("Credenziali Bybit mancanti")
        timestamp = str(int(time.time() * 1000) + self.clock_offset_ms)
        signed = f"{timestamp}{key}{self.receive_window}{wire}"
        signature = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        return {
            "X-BAPI-API-KEY": key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": str(self.receive_window),
            "X-BAPI-SIGN": signature,
            "X-BAPI-SIGN-TYPE": "2",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response | None = None) -> float:
        delay = min(8.0, 0.5 * 2**attempt) + random.uniform(0, 0.15)
        if response is not None:
            try:
                retry_after = float(response.headers.get("Retry-After", "0"))
                reset_ms = float(response.headers.get("X-Bapi-Limit-Reset-Timestamp", "0"))
                until_reset = reset_ms / 1000 - time.time()
                delay = max(delay, retry_after, until_reset)
            except ValueError:
                # Invalid rate-limit metadata never disables the local backoff.
                delay = max(delay, 1.0)
        return min(30.0, max(delay, 0.1))

    async def _request(
        self,
        method: str,
        path: str,
        data: dict,
        *,
        private: bool,
        order_intent: OrderIntent | None = None,
    ) -> dict:
        self._validate(mutation=method != "GET")
        order_create = private and method == "POST" and path == "/v5/order/create"
        if order_create and self._order_guard is not None and order_intent is None:
            raise OrderNotSentError(
                "Ordine non inviato: intenzione completa richiesta dal controllo sicurezza"
            )
        if not re.fullmatch(r"/v5/[a-z0-9/_-]+", path) or "//" in path:
            raise ValidationError("Percorso API non valido")
        if not private and not path.startswith("/v5/market/"):
            raise ValidationError("Endpoint pubblico non valido")
        endpoint = self.endpoints.rest if private else self.endpoints.public_rest
        normalized = _wire(data)
        query = str(httpx.QueryParams(sorted(normalized.items()))) if method == "GET" else ""
        body = (
            json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)
            if method != "GET"
            else ""
        )
        url = httpx.URL(endpoint + path).copy_with(query=query.encode())
        attempts = 4 if method == "GET" else 1
        for attempt in range(attempts):
            # Sign anew after any safe read retry; never log request headers or body.
            started = time.monotonic()
            try:
                async with self._semaphore:
                    # Authorization may have been revoked while a request was
                    # queued behind another request. Recheck before sending.
                    self._validate(mutation=method != "GET")
                    headers = self._headers(query if method == "GET" else body) if private else {}
                    if order_create and self._order_guard is not None:
                        if order_intent is None:
                            raise OrderNotSentError(
                                "Ordine non inviato: intenzione completa richiesta dal controllo sicurezza"
                            )
                        try:
                            result = self._order_guard(order_intent)
                            if result is not None:
                                if asyncio.iscoroutine(result):
                                    result.close()
                                elif isinstance(result, asyncio.Future):
                                    result.cancel()
                                raise RiskError(
                                    "Controllo sicurezza deve completarsi in modo sincrono"
                                )
                        except Exception as exc:
                            message = (
                                str(exc)
                                if isinstance(exc, RiskError)
                                else "Controllo sicurezza immediato fallito"
                            )
                            raise OrderNotSentError(f"Ordine non inviato: {message}") from exc
                    response = await self._client.request(
                        method, url, headers=headers, content=body.encode() if body else None
                    )
                self.latency_ms = round((time.monotonic() - started) * 1000, 2)
            except (httpx.RequestError, OSError) as exc:
                if method != "GET":
                    raise UncertainOrderError(
                        "Esito richiesta Bybit incerto: riconciliare prima di reinviare"
                    ) from exc
                if attempt + 1 < attempts:
                    await self._sleep(self._backoff(attempt))
                    continue
                raise NetworkError("Connessione Bybit non disponibile") from exc
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable:
                if method == "GET" and attempt + 1 < attempts:
                    await self._sleep(self._backoff(attempt, response))
                    continue
                if method != "GET" and response.status_code >= 500:
                    raise UncertainOrderError("Bybit 5xx: esito mutazione incerto, riconciliare")
                raise NetworkError(
                    f"Bybit temporaneamente non disponibile (HTTP {response.status_code})"
                )
            if response.status_code in {401}:
                raise AuthenticationError("Autenticazione Bybit fallita")
            if response.status_code == 404:
                raise BybitAPIError("Endpoint Bybit non disponibile", 10017)
            if response.status_code != 200:
                raise NetworkError(f"Accesso Bybit non disponibile (HTTP {response.status_code})")
            try:
                message = response.json()
                if not isinstance(message, dict) or "retCode" not in message:
                    raise ValueError("invalid envelope")
                raw_code = message["retCode"]
                if isinstance(raw_code, bool) or not (
                    isinstance(raw_code, int)
                    or isinstance(raw_code, str)
                    and re.fullmatch(r"-?[0-9]+", raw_code)
                ):
                    raise ValueError("invalid response code")
                code = int(raw_code)
            except (ValueError, TypeError) as exc:
                if method != "GET":
                    raise UncertainOrderError(
                        "Risposta Bybit invalida: esito mutazione incerto"
                    ) from exc
                raise NetworkError("Risposta Bybit non valida") from exc
            if code == 10006 and method == "GET" and attempt + 1 < attempts:
                await self._sleep(self._backoff(attempt, response))
                continue
            if code in {10003, 10004, 10007, 10010, 33004}:
                raise AuthenticationError(
                    "Autenticazione Bybit fallita: verificare chiave e ambiente"
                )
            if code == 10005:
                raise PermissionMissingError("Permessi API Bybit insufficienti", code)
            if method != "GET" and code in {10000, 10014, 10016, 110072}:
                raise UncertainOrderError(
                    f"Bybit retCode {code}: esito mutazione incerto, riconciliare"
                )
            if code:
                # retMsg may echo credentials or request content; expose only retCode.
                raise BybitAPIError(f"Bybit ha rifiutato la richiesta (retCode {code})", code)
            result = message.get("result")
            if not isinstance(result, dict):
                if method != "GET":
                    raise UncertainOrderError("Conferma mutazione Bybit incompleta")
                raise NetworkError("Risultato Bybit non valido")
            return result
        raise NetworkError("Richiesta Bybit non completata")

    async def public_get(self, path: str, params: dict) -> dict:
        return await self._request("GET", path, params, private=False)

    async def private_get(self, path: str, params: dict) -> dict:
        return await self._request("GET", path, params, private=True)

    async def private_post(self, path: str, payload: dict) -> dict:
        return await self._request("POST", path, payload, private=True)

    async def _pages(self, path: str, params: dict, *, private: bool = True) -> list[dict]:
        cursor = ""
        seen: set[str] = set()
        rows: list[dict] = []
        for _ in range(10000):
            payload = {**params, **({"cursor": cursor} if cursor else {})}
            result = await (
                self.private_get(path, payload) if private else self.public_get(path, payload)
            )
            page = result.get("list")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise ValidationError("Lista Bybit non valida")
            rows.extend(page)
            cursor = result.get("nextPageCursor", "") or ""
            if not cursor:
                return rows
            if not isinstance(cursor, str) or cursor in seen:
                raise ValidationError("Paginazione Bybit incoerente: riconciliazione bloccata")
            seen.add(cursor)
        raise ValidationError("Paginazione Bybit oltre limite di sicurezza")

    async def synchronize_clock(self) -> None:
        before = time.time() * 1000
        result = await self.public_get("/v5/market/time", {})
        after = time.time() * 1000
        try:
            server_ms = (
                int(result["timeNano"]) // 1_000_000
                if result.get("timeNano")
                else int(result["timeSecond"]) * 1000
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ValidationError("Clock Bybit non verificabile") from exc
        self.clock_offset_ms = round(server_ms - (before + after) / 2)
        if abs(self.clock_offset_ms) > 300000:
            raise ValidationError("Orologio locale fuori sincronizzazione: correggere data e ora")

    async def instrument(self, symbol: str) -> Instrument:
        rows = await self._pages(
            "/v5/market/instruments-info",
            {"category": self.category, "symbol": symbol},
            private=False,
        )
        matched = [row for row in rows if row.get("symbol") == symbol]
        if len(matched) != 1:
            raise ValidationError("Strumento Bybit non trovato o ambiguo")
        row = matched[0]
        if row.get("contractType") != "LinearPerpetual" or row.get("settleCoin") != "USDT":
            raise ValidationError("Il bot richiede un USDT perpetual linear")
        if row.get("status") != "Trading" or row.get("unifiedMarginTrade") is not True:
            raise ValidationError("Strumento non negoziabile con UTA")
        try:
            lots, prices, leverage = row["lotSizeFilter"], row["priceFilter"], row["leverageFilter"]
            return Instrument(
                symbol=symbol,
                tick_size=_decimal(prices["tickSize"], "tickSize", positive=True),
                qty_step=_decimal(lots["qtyStep"], "qtyStep", positive=True),
                min_qty=_decimal(lots["minOrderQty"], "minOrderQty", positive=True),
                max_qty=_decimal(lots["maxOrderQty"], "maxOrderQty", positive=True),
                max_market_qty=_decimal(lots["maxMktOrderQty"], "maxMktOrderQty", positive=True),
                min_notional=_decimal(lots["minNotionalValue"], "minNotionalValue", positive=True),
                min_leverage=_decimal(leverage["minLeverage"], "minLeverage", positive=True),
                max_leverage=_decimal(leverage["maxLeverage"], "maxLeverage", positive=True),
                status=row["status"],
            )
        except KeyError as exc:
            raise ValidationError("Regole strumento Bybit incomplete") from exc

    async def ticker(self, symbol: str) -> Decimal:
        rows = await self._pages(
            "/v5/market/tickers", {"category": self.category, "symbol": symbol}, private=False
        )
        matched = [row for row in rows if row.get("symbol") == symbol]
        if len(matched) != 1:
            raise ValidationError("Prezzo Bybit non verificabile")
        return _decimal(matched[0].get("lastPrice"), "lastPrice", positive=True)

    async def candles(self, symbol: str, interval: str = "15", limit: int = 200) -> list[dict]:
        if (
            interval
            not in {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"}
            or not 1 <= limit <= 1000
        ):
            raise ValidationError("Parametri candele non validi")
        result = await self.public_get(
            "/v5/market/kline",
            {"category": self.category, "symbol": symbol, "interval": interval, "limit": limit},
        )
        rows = result.get("list")
        if not isinstance(rows, list):
            raise ValidationError("Candele Bybit non valide")
        candles = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                raise ValidationError("Candela Bybit incompleta")
            try:
                candle = {"time": int(row[0]) // 1000}
            except (TypeError, ValueError) as exc:
                raise ValidationError("Timestamp candela Bybit non valido") from exc
            candle.update(
                {
                    field: str(_decimal(value, field, positive=field != "volume"))
                    for field, value in zip(
                        ("open", "high", "low", "close", "volume"), row[1:6], strict=True
                    )
                }
            )
            low, high = Decimal(candle["low"]), Decimal(candle["high"])
            if (
                not low <= Decimal(candle["open"]) <= high
                or not low <= Decimal(candle["close"]) <= high
                or Decimal(candle["volume"]) < 0
            ):
                raise ValidationError("Geometria candela Bybit non valida")
            candles.append(candle)
        return sorted(candles, key=lambda candle: candle["time"])

    async def midnight_mark(self, symbol: str, day_start_ms: int) -> Decimal:
        """Exact UTC-day opening mark; current price is never a substitute."""
        now = int(time.time() * 1000) + self.clock_offset_ms
        if (
            isinstance(day_start_ms, bool)
            or not isinstance(day_start_ms, int)
            or day_start_ms < 0
            or day_start_ms % 86400000
            or day_start_ms > now
        ):
            raise ValidationError("Inizio giorno UTC non valido")
        result = await self.public_get(
            "/v5/market/mark-price-kline",
            {
                "category": self.category,
                "symbol": symbol,
                "interval": "1",
                "start": day_start_ms,
                "end": day_start_ms + 59999,
                "limit": 1,
            },
        )
        if result.get("symbol") != symbol or result.get("category") != self.category:
            raise ValidationError("Ambito mark-price kline Bybit incoerente")
        rows = result.get("list")
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], list)
            or len(rows[0]) != 5
        ):
            raise ValidationError("Mark price di mezzanotte UTC non verificabile")
        row = rows[0]
        try:
            timestamp = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValidationError("Timestamp mark-price kline Bybit non valido") from exc
        if timestamp != day_start_ms:
            raise ValidationError("Mark price di mezzanotte UTC assente: nessun fallback")
        opening = _decimal(row[1], "opening mark", positive=True)
        high = _decimal(row[2], "mark high", positive=True)
        low = _decimal(row[3], "mark low", positive=True)
        closing = _decimal(row[4], "mark close", positive=True)
        if not low <= opening <= high or not low <= closing <= high:
            raise ValidationError("Mark-price kline Bybit non valida")
        return opening

    async def positions(self, symbol: str) -> list[dict]:
        return await self._pages(
            "/v5/position/list", {"category": self.category, "symbol": symbol, "limit": 200}
        )

    async def open_orders(self, symbol: str) -> list[dict]:
        return await self._pages(
            "/v5/order/realtime",
            {"category": self.category, "symbol": symbol, "openOnly": 0, "limit": 50},
        )

    async def executions(self, symbol: str, start_time: int | None = None) -> list[dict]:
        # Funding/cash movements use the transaction ledger, never trade qty.
        params = {"category": self.category, "symbol": symbol, "execType": "Trade", "limit": 100}
        queries = [params]
        if start_time is not None:
            now = int(time.time() * 1000) + self.clock_offset_ms
            if start_time < 0 or start_time > now:
                raise ValidationError("Intervallo executions non valido")
            queries = []
            for start, end in _history_windows(start_time, now, 3 * 86400000):
                query = {**params, "startTime": start}
                if end is not None:
                    query["endTime"] = end
                queries.append(query)
        rows: dict[str, dict] = {}
        for query in queries:
            page = await self._pages("/v5/execution/list", query)
            for row in page:
                execution_id = row.get("execId")
                if (
                    not isinstance(execution_id, str)
                    or not 1 <= len(execution_id) <= 256
                    or not execution_id.isprintable()
                    or execution_id.strip() != execution_id
                ):
                    raise ValidationError("Execution Bybit senza ID valido")
                previous = rows.get(execution_id)
                if previous is not None and previous != row:
                    raise ValidationError("Execution Bybit duplicata con dati incoerenti")
                rows[execution_id] = row
        return sorted(rows.values(), key=lambda row: (int(row.get("execTime", 0)), row["execId"]))

    async def find_order(self, symbol: str, order_link_id: str) -> dict | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,36}", order_link_id):
            raise ValidationError("Order link ID non valido")
        params = {
            "category": self.category,
            "symbol": symbol,
            "orderLinkId": order_link_id,
            "limit": 50,
        }
        for path in ("/v5/order/realtime", "/v5/order/history"):
            rows = await self._pages(path, params)
            matching = [row for row in rows if row.get("orderLinkId") == order_link_id]
            if matching:
                order_ids = {row.get("orderId") for row in matching}
                if len(order_ids) != 1 or None in order_ids or "" in order_ids:
                    raise ValidationError("Order link ID ambiguo su Bybit")
                return max(matching, key=lambda row: int(row.get("updatedTime", "0")))
        return None

    async def transactions(self, symbol: str, start_time: int | None = None) -> list[dict]:
        """Read UTA cash movements; funding never changes executed position qty.

        `funding` is signed positive received/negative paid. `cashFlow` does not
        include funding or trading fees. Return provider IDs for DB idempotence.
        A missing endpoint is an error, not an assumption of zero funding.
        """
        params = {
            "accountType": "UNIFIED",
            "category": self.category,
            "currency": "USDT",
            "limit": 50,
        }
        now = int(time.time() * 1000) + self.clock_offset_ms
        if start_time is not None and (start_time < 0 or start_time > now):
            raise ValidationError("Intervallo transaction log non valido")
        windows = (
            [(None, None)]
            if start_time is None
            else _history_windows(start_time, now, 12 * 3600000)
        )
        records: dict[str, dict] = {}
        for start, end in windows:
            query = dict(params)
            if start is not None:
                query["startTime"] = start
            if end is not None:
                query["endTime"] = end
            rows = await self._pages("/v5/account/transaction-log", query)
            for row in rows:
                if row.get("symbol") != symbol:
                    continue
                if row.get("category") != self.category or row.get("currency") != "USDT":
                    raise ValidationError("Ambito transaction log Bybit incoerente")
                transaction_id = row.get("id")
                if not isinstance(transaction_id, str) or not 1 <= len(transaction_id) <= 256:
                    raise ValidationError("Transaction log Bybit senza ID valido")
                try:
                    timestamp = int(row["transactionTime"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValidationError("Timestamp transaction log Bybit non valido") from exc
                if timestamp < 0:
                    raise ValidationError("Timestamp transaction log Bybit non valido")
                normalized = {**row, "transactionTime": str(timestamp)}
                for field in ("funding", "fee", "cashFlow", "change"):
                    if field not in row:
                        raise ValidationError("Transaction log Bybit incompleto")
                    normalized[field] = format(_decimal(row[field] or "0", field), "f")
                previous = records.get(transaction_id)
                if previous is not None and previous != normalized:
                    raise ValidationError("Transaction log Bybit duplicato con dati incoerenti")
                records[transaction_id] = normalized
        return sorted(records.values(), key=lambda row: (int(row["transactionTime"]), row["id"]))

    async def account(self) -> AccountInfo:
        from gridbot.account import AccountService

        return await AccountService(self).fetch()

    async def create_order(self, intent: OrderIntent) -> dict:
        if intent.environment != self.environment:
            raise ValidationError("Ambiente ordine e adapter non corrispondono")
        if intent.order_type not in {"Market", "Limit"}:
            raise ValidationError("Tipo ordine non supportato")
        _decimal(intent.qty, "qty", positive=True)
        payload = {
            "category": self.category,
            "symbol": intent.symbol,
            "side": intent.side.closing_side if intent.reduce_only else intent.side.opening_side,
            "positionIdx": intent.side.position_idx,
            "orderType": intent.order_type,
            "qty": format(intent.qty, "f"),
            "orderLinkId": intent.order_link_id,
            "reduceOnly": intent.reduce_only,
            "timeInForce": "IOC" if intent.order_type == "Market" else "GTC",
        }
        if intent.order_type == "Limit":
            if intent.price is None:
                raise ValidationError("Ordine Limit richiede prezzo")
            payload["price"] = format(_decimal(intent.price, "price", positive=True), "f")
        else:
            slippage = _decimal(intent.slippage_pct, "slippageTolerance", positive=True)
            if not Decimal("0.01") <= slippage <= Decimal("10"):
                raise ValidationError("Slippage tolerance Bybit non valida")
            payload["slippageToleranceType"] = "Percent"
            payload["slippageTolerance"] = format(slippage, "f")
        result = await self._request(
            "POST", "/v5/order/create", payload, private=True, order_intent=intent
        )
        if (
            not isinstance(result.get("orderId"), str)
            or not 1 <= len(result["orderId"]) <= 128
            or result.get("orderLinkId") != intent.order_link_id
        ):
            raise UncertainOrderError("Conferma ordine Bybit incompleta: riconciliare")
        return {"orderId": result["orderId"], "orderLinkId": result["orderLinkId"]}

    async def cancel_order(self, symbol: str, order_id: str, order_link_id: str) -> dict:
        if not order_id and not order_link_id:
            raise ValidationError("Cancellazione richiede Order ID o Order link ID")
        payload = {"category": self.category, "symbol": symbol}
        if order_id:
            payload["orderId"] = order_id
        if order_link_id:
            payload["orderLinkId"] = order_link_id
        result = await self.private_post("/v5/order/cancel", payload)
        if (
            not isinstance(result.get("orderId"), str)
            or not result["orderId"]
            or (order_id and result["orderId"] != order_id)
        ):
            raise UncertainOrderError("Conferma cancellazione Bybit incompleta: riconciliare")
        return result

    async def set_leverage(self, symbol: str, leverage: Decimal) -> None:
        leverage = _decimal(leverage, "leverage", positive=True)
        positions = await self.positions(symbol)
        relevant = [row for row in positions if row.get("symbol") == symbol]
        if {row.get("positionIdx") for row in relevant} != {1, 2}:
            raise HedgeModeError("Leverage richiede Hedge Mode verificato")
        if all(
            _decimal(row.get("leverage"), "leverage", positive=True) == leverage for row in relevant
        ):
            return
        if any(_decimal(row.get("size"), "position size") > 0 for row in relevant):
            raise RiskError("Non modificare leverage con posizioni BTCUSDT esistenti")
        if await self.open_orders(symbol):
            raise RiskError("Non modificare leverage con ordini BTCUSDT esistenti")
        try:
            await self.private_post(
                "/v5/position/set-leverage",
                {
                    "category": self.category,
                    "symbol": symbol,
                    "buyLeverage": format(leverage, "f"),
                    "sellLeverage": format(leverage, "f"),
                },
            )
        except BybitAPIError as exc:
            if exc.ret_code != 110043:
                raise
        observed = await self.positions(symbol)
        observed_relevant = [row for row in observed if row.get("symbol") == symbol]
        if {row.get("positionIdx") for row in observed_relevant} != {1, 2} or any(
            _decimal(row.get("leverage"), "leverage", positive=True) != leverage
            for row in observed_relevant
        ):
            raise RiskError("Leverage Bybit non corrisponde al valore richiesto")

    async def close(self) -> None:
        await self._client.aclose()


class BybitDemoAdapter(BybitAdapter):
    def __init__(self, credentials: Credentials, **kwargs: Any) -> None:
        if credentials.environment != Environment.DEMO:
            raise ValidationError("Bybit Demo richiede credenziali DEMO")
        super().__init__(credentials, **kwargs)


class BybitMainnetAdapter(BybitAdapter):
    def __init__(self, credentials: Credentials, **kwargs: Any) -> None:
        if credentials.environment != Environment.MAINNET:
            raise ValidationError("Bybit Mainnet richiede credenziali LIVE")
        super().__init__(credentials, **kwargs)


def create_adapter(credentials: Credentials, **kwargs: Any) -> BybitAdapter:
    adapter = (
        BybitDemoAdapter if credentials.environment == Environment.DEMO else BybitMainnetAdapter
    )
    return adapter(credentials, **kwargs)
