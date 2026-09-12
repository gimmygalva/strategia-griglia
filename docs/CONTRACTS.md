# Shared implementation contracts — 0.1.0 development

Python package: backend/gridbot. Imports: gridbot.models, gridbot.errors.
All money/prices/quantities Decimal. UTC ms for exchange events, ISO UTC for audit.
Only DEMO and LIVE values; Environment.MAINNET serializes LIVE.

## Python interfaces

Exchange adapter (async):
- environment: Environment; endpoints: Endpoints
- public_get(path: str, params: dict) -> dict (Bybit result object)
- private_get(path: str, params: dict) -> dict
- private_post(path: str, payload: dict) -> dict (NO blind retries for mutations)
- instrument(symbol) -> Instrument
- ticker(symbol) -> Decimal
- candles(symbol, interval='15', limit=200) -> list[dict]: {time seconds,open,high,low,close,volume strings}
- account() -> AccountInfo
- open_orders(symbol) -> list[dict]; positions(symbol) -> list[dict]
- executions(symbol, start_time: int|None=None) -> list[dict]
- find_order(symbol, order_link_id) -> dict|None (realtime AND history; full pagination)
- create_order(intent: OrderIntent) -> dict {orderId,orderLinkId}
- cancel_order(symbol, order_id, order_link_id) -> dict
- set_leverage(symbol, leverage: Decimal) -> None (never silently modify position mode)
- close() -> None
Credentials not persisted except OS Keychain. Adapter accepts Credentials(env,key,secret).
WebSocketManager(adapter, symbol, on_event async callback, on_status async callback).
.start(); .stop(). Callback event is raw dict; market event normalized topic tickers.BTCUSDT;
status callback(source: str, connected: bool). MUST authenticate private then subscribe.

Quant modules:
GridEngine(anchor: Decimal, spacing: Decimal FRACTION, levels: int, tick_size: Decimal,
 hysteresis: Decimal, debounce_ms: int).
.levels -> list[GridLevel] (2X levels, exclude current center, integer index, absolute price)
.on_price(price: Decimal, timestamp_ms: int) -> list[GridTouch] (index, price, sequence)
.shift(price) -> bool; .snapshot() -> dict; .restore(snapshot) -> GridEngine.
Touch IDs persist before order send. Tick offsets anchor + index * anchor*spacing; fixed absolute lattice.
RiskEngine.validate_order(intent, context: RiskContext, limits: StrategyConfig, instrument) -> None; raises RiskError.
InjectionCalculator.calculate(side: Side,current_qty,average,market,target_average,entry_fees=0,
 fee_rate=0.0006,slippage=0.001,profit_target=0) -> InjectionPlan.
break_even(side,qty,average,fees,exit_fee_rate,exit_slippage,profit_target=0) -> Decimal.
RecoveryEngine.analyze(lots: list[dict], market: Decimal, config: StrategyConfig, instrument) -> list[dict].
lots keys: side ('LONG'/'SHORT'),qty,entry,fees,pair_id,order_link_id; ONLY remaining executed qty.
SupportResistanceEngine.analyze(candles: list[dict], price: Decimal) -> dict.

## Backend API — frontend contract

All JSON amounts are decimal strings or null. Never zero placeholders when disconnected.
GET /api/health {version,status:'ok',environment:'DEMO'|'LIVE',mainnet_allowed:bool}
GET /api/state ->
{environment, status:'DISCONNECTED'|'READY'|'RUNNING'|'PAUSED'|'DEGRADED'|'RECONCILING',
 connected:bool, public_connected:bool,private_connected:bool,latency_ms:number|null,
 error:string|null,account:AccountInfo|null,price:string|null,
 config:StrategyConfig,grid:list[{index,price}],positions:list[dict],
 recovery:list[dict],portfolio:{equity,realized,unrealized,fees,net,today,grid,recovery,long,short} [all string|null],
 candles:list[dict],wizard_completed:bool,mainnet_allowed:bool}
GET /api/events -> list[{id,time,title,event,details}] latest 250
GET /api/orders -> list[dict]
GET /api/candles?interval=15 -> list[{time,open,high,low,close,volume}]
POST /api/credentials {environment,api_key,api_secret} -> {saved:true} secret write-only
POST /api/connect {environment:'DEMO'|'LIVE'} -> {account,status} validates UTA/permissions/hedge; no trading
POST /api/config StrategyConfig full model -> {config}
POST /api/start {live_confirm?:'AVVIA LIVE',live_ack?:true} -> {status}
POST /api/pause {} -> {status} cancel only own pending entries; preserve TP
POST /api/recovery {side:'LONG'|'SHORT',confirm:true} -> {status}
POST /api/close-all {confirm:'CHIUDI TUTTO',ack:true} -> {status}; own symbol positions only, double UI confirmation
POST /api/wizard {completed:true} -> {saved:true}
Errors HTTP {detail:{code,message}}. Invalid config 422. Never echo credential request.

WS /api/ws: authenticate first frame {type:'authenticate',token:string} OR bootstrap HttpOnly cookie.
Then server frames {type:'state',data:state}, {type:'event',data:event}; reconnect, no synthetic data.
Desktop Tauri command bootstrap -> {url:'http://127.0.0.1:port',token:string}.
Browser development served backend same origin. GET /bootstrap/<ephemeral_token> sets HttpOnly Strict cookie and redirect /.
Frontend auth api module attempts @tauri-apps/api/core invoke('bootstrap'); falls back same-origin cookie.
No secrets in localStorage, logs, exported config, backend responses or URL.
