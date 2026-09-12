"""Fail-closed order validation shared by DEMO and LIVE adapters."""

from decimal import Decimal

from .errors import RiskError, ValidationError
from .grid import decimal_value, round_down
from .models import Environment, Instrument, OrderIntent, RiskContext, StrategyConfig


class RiskEngine:
    @staticmethod
    def validate_order(
        intent: OrderIntent,
        context: RiskContext,
        limits: StrategyConfig,
        instrument: Instrument,
    ) -> None:
        def require(condition: bool, message: str) -> None:
            if not condition:
                raise RiskError(message)

        require(intent.environment == context.environment, "Environment mismatch: HARD STOP")
        if intent.environment == Environment.MAINNET:
            require(
                context.mainnet_allowed and context.live_confirmed,
                "LIVE non autorizzato dal backend e dalla UI",
            )
        require(context.connected, "Exchange non connesso: nessun nuovo ordine")
        require(context.reconciled, "Stato exchange incerto: riconciliazione obbligatoria")
        require(context.permissions, "Permessi trading mancanti")
        require(context.hedge_mode, "Hedge Mode non verificato")
        require(not context.duplicate, "OrderLinkId già esistente")
        require(intent.symbol == limits.symbol == instrument.symbol, "Symbol non coerente")
        require(instrument.status == "Trading", "Instrument non negoziabile")
        require(intent.order_type in ("Market", "Limit"), "Tipo ordine non supportato")
        require(
            intent.order_type != "Limit" or intent.price is not None, "Limit order senza prezzo"
        )
        require(
            intent.order_type != "Market" or intent.price is None,
            "Market order con limit price ambiguo",
        )

        try:
            qty = decimal_value(intent.qty, "qty")
            price = decimal_value(
                intent.price if intent.price is not None else context.market_price, "price"
            )
            market = decimal_value(context.market_price, "market")
            step = decimal_value(instrument.qty_step, "qtyStep")
            tick = decimal_value(instrument.tick_size, "tickSize")
            min_qty, max_qty = decimal_value(instrument.min_qty), decimal_value(instrument.max_qty)
            max_market_qty = decimal_value(instrument.max_market_qty)
            min_notional = decimal_value(instrument.min_notional)
            fee = decimal_value(context.taker_fee)
            slip = decimal_value(intent.slippage_pct) / 100
            configured_slip = decimal_value(limits.slippage_pct) / 100
            balance = decimal_value(context.available_balance)
            exposure = decimal_value(context.total_exposure)
            recovery = decimal_value(context.recovery_exposure)
            reserved = decimal_value(context.reserved_notional)
            daily_pnl = decimal_value(context.daily_pnl)
            owned_qty = decimal_value(context.position_qty)
            leverage = decimal_value(limits.leverage)
            min_leverage, max_leverage = (
                decimal_value(instrument.min_leverage),
                decimal_value(instrument.max_leverage),
            )
        except ValidationError as exc:
            raise RiskError(f"Input rischio non valido: {exc}") from exc
        require(price > 0 and market > 0 and qty > 0, "Prezzo/quantità non positivi")
        require(
            step > 0
            and tick > 0
            and min_qty > 0
            and max_qty >= min_qty
            and max_market_qty >= min_qty,
            "Limiti instrument incoerenti",
        )
        require(
            min_notional >= 0 and 0 <= fee < 1 and 0 <= slip < 1,
            "Fee/slippage/limiti instrument incoerenti",
        )
        require(slip <= configured_slip, "Slippage ordine supera limite configurato")
        require(min_leverage <= leverage <= max_leverage, "Leverage incompatibile con instrument")
        require(qty == round_down(qty, step), "Qty non allineata a qtyStep")
        require(min_qty <= qty <= max_qty, "Qty fuori min/max instrument")
        require(
            intent.order_type != "Market" or qty <= max_market_qty, "Qty supera maxMarketOrderQty"
        )
        require(
            intent.price is None or price == round_down(price, tick),
            "Prezzo non allineato a tickSize",
        )
        require(
            exposure >= 0 and recovery >= 0 and reserved >= 0 and owned_qty >= 0,
            "Stato exposure/riserva non valido",
        )

        # A reduce-only order must never be larger than the reconciled position owned
        # by this bot. Loss/paused status must not prevent reducing that position.
        if intent.reduce_only:
            require(
                owned_qty > 0 and qty <= owned_qty,
                "Reduce-only supera posizione di proprietà del bot",
            )
            require(
                intent.purpose in ("TP", "RECOVERY_TP", "CLOSE"),
                "Purpose reduce-only non consentito",
            )
            return

        require(context.running, "Bot fermo: nuovi ingressi bloccati")
        require(balance >= 0, "Saldo disponibile non valido")
        require(
            daily_pnl > -limits.max_daily_loss_usdt,
            "Max Daily Loss raggiunta: nuovi ingressi sospesi",
        )
        require(
            intent.purpose in ("GRID", "INITIAL", "RECOVERY"), "Purpose ingresso non consentito"
        )
        notional = qty * price
        minimum_value_price = market
        if intent.order_type == "Limit":
            minimum_value_price = (
                min(price, market * Decimal("1.05"))
                if intent.side.opening_side == "Buy"
                else max(price, market * Decimal("0.95"))
            )
        require(
            qty * minimum_value_price >= min_notional, "Notional inferiore al minimo instrument"
        )
        if intent.purpose in ("GRID", "INITIAL"):
            require(notional <= limits.order_size_usdt, "Dimensione ordine supera Order Size")
        else:
            require(
                qty * market * (1 + slip) <= limits.max_injection_usdt,
                "Injection supera Max Injection",
            )

        # Gross exposure includes both hedge sides; hedging must not conceal margin.
        # Reserve all acknowledgements which have not been reconciled into positions.
        adverse_notional = qty * max(market, price) * (1 + slip)
        conservative_reserved = reserved * (1 + configured_slip)
        require(
            exposure + conservative_reserved + adverse_notional <= limits.max_exposure_usdt,
            "Max Total Exposure superata",
        )
        if intent.purpose == "RECOVERY":
            require(
                recovery + conservative_reserved + adverse_notional
                <= limits.max_recovery_exposure_usdt,
                "Max Recovery Exposure superata",
            )
        collateral = (adverse_notional + conservative_reserved) / leverage
        collateral += (adverse_notional + conservative_reserved) * fee * 2
        require(
            collateral <= balance, "Saldo insufficiente includendo ordini riservati, fee e slippage"
        )

    # Public spelling requested in the specification; one implementation only.
    validateOrder = validate_order
