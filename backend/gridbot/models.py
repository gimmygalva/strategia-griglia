from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Environment(StrEnum):
    DEMO = "DEMO"
    MAINNET = "LIVE"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def position_idx(self) -> int:
        return 1 if self == Side.LONG else 2

    @property
    def opening_side(self) -> str:
        return "Buy" if self == Side.LONG else "Sell"

    @property
    def closing_side(self) -> str:
        return "Sell" if self == Side.LONG else "Buy"


class Credentials(BaseModel):
    environment: Environment
    api_key: SecretStr
    api_secret: SecretStr


class Instrument(BaseModel):
    symbol: str
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    max_qty: Decimal
    max_market_qty: Decimal
    min_notional: Decimal
    min_leverage: Decimal = Decimal("1")
    max_leverage: Decimal = Decimal("1")
    status: str = "Trading"


class AccountInfo(BaseModel):
    uid: str
    account_type: str
    uta_status: int
    equity: Decimal
    available_balance: Decimal
    hedge_mode: bool
    permissions: bool
    leverage_long: Decimal
    leverage_short: Decimal
    taker_fee: Decimal = Decimal("0.0006")
    maker_fee: Decimal = Decimal("0.0006")
    fee_source: str = "conservative estimate"


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(default="BTCUSDT", pattern="^BTCUSDT$")
    order_size_usdt: Decimal = Field(default=Decimal("100"), gt=0)
    levels: int = Field(default=20, ge=1, le=100)
    spacing_pct: Decimal = Field(default=Decimal("0.50"), gt=0, le=5)
    tp_pct: Decimal = Field(default=Decimal("1.00"), gt=0, le=20)
    leverage: Decimal = Field(default=Decimal("1"), ge=1, le=3)
    initial_pair: bool = True
    hysteresis_ticks: int = Field(default=5, ge=1, le=1000)
    debounce_ms: int = Field(default=3000, ge=100, le=60000)
    recovery_threshold_pct: Decimal = Field(default=Decimal("3"), gt=0, le=50)
    max_injection_usdt: Decimal = Field(default=Decimal("500"), gt=0)
    max_recovery_exposure_usdt: Decimal = Field(default=Decimal("2000"), gt=0)
    max_exposure_usdt: Decimal = Field(default=Decimal("5000"), gt=0)
    max_daily_loss_usdt: Decimal = Field(default=Decimal("100"), gt=0)
    recovery_profit_target_usdt: Decimal = Field(default=Decimal("1"), ge=0)
    recovery_retrace_pct: Decimal = Field(default=Decimal("1"), gt=0, le=10)
    slippage_pct: Decimal = Field(default=Decimal("0.10"), ge=Decimal("0.01"), le=1)
    support_resistance_timeframe: str = Field(default="15", pattern="^(1|5|15|30|60|240|D)$")
    auto_recovery: bool = False

    @model_validator(mode="after")
    def check_geometry(self):
        if self.levels * self.spacing_pct >= 95:
            raise ValueError("Finestra grid troppo ampia")
        if self.max_recovery_exposure_usdt > self.max_exposure_usdt:
            raise ValueError("Recovery exposure supera exposure totale")
        return self


class OrderIntent(BaseModel):
    environment: Environment
    symbol: str
    order_link_id: str = Field(max_length=36, min_length=1, pattern="^[A-Za-z0-9_-]+$")
    side: Side
    qty: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    order_type: str = "Market"
    reduce_only: bool = False
    purpose: str = "GRID"
    pair_id: str | None = None
    level_id: str | None = None
    parent_link_id: str | None = None
    slippage_pct: Decimal = Decimal("0.10")


class RiskContext(BaseModel):
    environment: Environment
    connected: bool
    running: bool
    reconciled: bool
    permissions: bool
    hedge_mode: bool
    available_balance: Decimal
    total_exposure: Decimal
    recovery_exposure: Decimal
    daily_pnl: Decimal
    market_price: Decimal
    reserved_notional: Decimal = Decimal("0")
    duplicate: bool = False
    mainnet_allowed: bool = False
    live_confirmed: bool = False
    position_qty: Decimal = Decimal("0")
    taker_fee: Decimal = Decimal("0.0006")


class GridLevel(BaseModel):
    index: int
    price: Decimal


class GridTouch(BaseModel):
    index: int
    price: Decimal
    sequence: int


class InjectionPlan(BaseModel):
    side: Side
    required_qty: Decimal
    required_usdt: Decimal
    new_average: Decimal
    break_even: Decimal
    target_average: Decimal
    estimated_fees: Decimal
    effective_price: Decimal
    profit_target: Decimal
