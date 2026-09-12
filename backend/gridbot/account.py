"""Verified UTA account, permission, Hedge Mode and fee discovery."""

import hmac
from decimal import Decimal
from typing import TYPE_CHECKING

from gridbot.errors import AuthenticationError, BybitAPIError, ValidationError
from gridbot.exchange import AccountTypeError, HedgeModeError, PermissionMissingError, _decimal
from gridbot.models import AccountInfo, Environment

if TYPE_CHECKING:
    from gridbot.exchange import BybitAdapter


class AccountService:
    def __init__(self, adapter: "BybitAdapter") -> None:
        self.adapter = adapter

    async def fetch(self) -> AccountInfo:
        adapter = self.adapter
        await adapter.synchronize_clock()
        key_info = await adapter.private_get("/v5/user/query-api", {})
        echoed_key = key_info.get("apiKey")
        if echoed_key and not hmac.compare_digest(
            str(echoed_key), adapter.credentials.api_key.get_secret_value()
        ):
            raise AuthenticationError("Identità API Bybit incoerente")
        permissions = key_info.get("permissions")
        if not isinstance(permissions, dict) or key_info.get("readOnly") not in {0, "0"}:
            raise PermissionMissingError("API deve consentire Read/Write e trading derivatives")
        contract = set(permissions.get("ContractTrade", []))
        derivatives = set(permissions.get("Derivatives", []))
        if not ({"Order", "Position"} <= contract or "DerivativesTrade" in derivatives):
            raise PermissionMissingError("Permessi Order/Position o DerivativesTrade mancanti")
        uid = key_info.get("userID")
        if uid is None or not str(uid).isdigit() or int(uid) <= 0:
            raise AccountTypeError("UID account Bybit non verificabile")
        info = await adapter.private_get("/v5/account/info", {})
        try:
            status = int(info.get("unifiedMarginStatus", 0))
        except (TypeError, ValueError) as exc:
            raise AccountTypeError("UTA status Bybit non valido") from exc
        if status not in {3, 4, 5, 6}:
            raise AccountTypeError("È richiesto un Bybit Unified Trading Account")
        if info.get("marginMode") != "REGULAR_MARGIN":
            raise AccountTypeError(
                "MVP richiede UTA Cross Margin; Isolated e Portfolio non supportati"
            )
        wallet_rows = await adapter._pages(
            "/v5/account/wallet-balance", {"accountType": "UNIFIED", "coin": "USDT"}
        )
        if len(wallet_rows) != 1 or wallet_rows[0].get("accountType") != "UNIFIED":
            raise AccountTypeError("Wallet UTA non verificabile")
        wallet = wallet_rows[0]
        coins = wallet.get("coin", [])
        usdt = [coin for coin in coins if coin.get("coin") == "USDT"]
        if len(usdt) != 1:
            raise AccountTypeError("Saldo USDT UTA non verificabile")
        equity = _decimal(wallet.get("totalEquity"), "totalEquity")
        available_usd = _decimal(wallet.get("totalAvailableBalance"), "totalAvailableBalance")
        # Equity and non-USDT collateral are never treated as free USDT cash.
        cash = _decimal(usdt[0].get("walletBalance"), "USDT walletBalance")
        borrowed = _decimal(usdt[0].get("spotBorrow", "0"), "USDT spotBorrow")
        available = max(Decimal("0"), min(available_usd, cash - borrowed))
        positions = await adapter.positions("BTCUSDT")
        matching = [position for position in positions if position.get("symbol") == "BTCUSDT"]
        if len(matching) != 2 or {position.get("positionIdx") for position in matching} != {1, 2}:
            raise HedgeModeError("Attivare Hedge Mode per BTCUSDT su Bybit prima di avviare")
        indexed = {position["positionIdx"]: position for position in matching}
        leverage_long = _decimal(indexed[1].get("leverage"), "Long leverage", positive=True)
        leverage_short = _decimal(indexed[2].get("leverage"), "Short leverage", positive=True)
        fee_source = "Bybit account fee-rate API"
        try:
            fee_rows = await adapter._pages(
                "/v5/account/fee-rate", {"category": adapter.category, "symbol": "BTCUSDT"}
            )
            matching_fees = [row for row in fee_rows if row.get("symbol") in {"BTCUSDT", ""}]
            if len(matching_fees) != 1:
                raise ValidationError("Commissioni account Bybit non verificabili")
            taker = _decimal(matching_fees[0].get("takerFeeRate"), "takerFeeRate")
            maker = _decimal(matching_fees[0].get("makerFeeRate"), "makerFeeRate")
            if not Decimal("0") <= taker < Decimal("0.01") or not Decimal(
                "-0.01"
            ) < maker < Decimal("0.01"):
                raise ValidationError("Commissioni Bybit fuori intervallo di sicurezza")
        except BybitAPIError as exc:
            if adapter.environment != Environment.DEMO or exc.ret_code != 10017:
                raise
            taker = maker = Decimal("0.0006")
            fee_source = (
                "Conservative estimate: Demo fee-rate API unsupported; actual fees from executions"
            )
        return AccountInfo(
            uid=str(uid),
            account_type="UNIFIED",
            uta_status=status,
            equity=equity,
            available_balance=available,
            hedge_mode=True,
            permissions=True,
            leverage_long=leverage_long,
            leverage_short=leverage_short,
            taker_fee=taker,
            maker_fee=maker,
            fee_source=fee_source,
        )
