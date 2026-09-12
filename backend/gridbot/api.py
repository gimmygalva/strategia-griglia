import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.cors import CORSMiddleware

from . import __version__
from .errors import BotError
from .models import Credentials, Environment, Side, StrategyConfig


class CredentialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: Environment
    api_key: SecretStr = Field(min_length=4, max_length=256)
    api_secret: SecretStr = Field(min_length=4, max_length=512)


class ConnectInput(BaseModel):
    environment: Environment


class StartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    live_confirm: str | None = None
    live_ack: bool = False


class RecoveryInput(BaseModel):
    side: Side
    confirm: bool = False


class CloseInput(BaseModel):
    confirm: str
    ack: bool = False


class WizardInput(BaseModel):
    completed: bool


def create_app(
    runtime,
    token: str,
    port: int,
    frontend_dir: Path | None = None,
    shutdown_callback=None,
    test_origin: str | None = None,
) -> FastAPI:
    own_origin = f"http://127.0.0.1:{port}"
    allowed_origins = {
        own_origin,
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    }
    allowed_hosts = {f"127.0.0.1:{port}"}
    if test_origin:
        from urllib.parse import urlsplit

        allowed_origins.add(test_origin)
        allowed_hosts.add(urlsplit(test_origin).netloc)

    @asynccontextmanager
    async def lifespan(app):
        await runtime.initialize()
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(
        title="Grid Hedge Bot local API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorized(headers, cookies):
        bearer = headers.get("authorization", "")
        value = bearer[7:] if bearer.startswith("Bearer ") else cookies.get("grid_session", "")
        return bool(value) and hmac.compare_digest(value, token)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse(
                {"detail": {"code": "INVALID_HOST", "message": "Host locale non valido"}}, 403
            )
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            return JSONResponse(
                {"detail": {"code": "INVALID_ORIGIN", "message": "Origine non autorizzata"}}, 403
            )
        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            if not authorized(request.headers, request.cookies):
                return JSONResponse(
                    {
                        "detail": {
                            "code": "UNAUTHORIZED",
                            "message": "Autenticazione locale richiesta",
                        }
                    },
                    401,
                )
            if request.method == "POST" and not origin:
                # Native desktop bearer requests do not have a browser Origin; cookie
                # mutations always require one, preventing CSRF via form submission.
                if not request.headers.get("authorization", "").startswith("Bearer "):
                    return JSONResponse(
                        {"detail": {"code": "ORIGIN_REQUIRED", "message": "Origine richiesta"}}, 403
                    )
            size = request.headers.get("content-length")
            if size and int(size) > 32768:
                return JSONResponse(
                    {"detail": {"code": "REQUEST_TOO_LARGE", "message": "Richiesta troppo grande"}},
                    413,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' ws://127.0.0.1:* http://127.0.0.1:*; "
            "frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default response echoes input; never echo credential fields.
        return JSONResponse(
            {
                "detail": {
                    "code": "VALIDATION_ERROR",
                    "message": "Dati non validi",
                    "fields": [".".join(str(v) for v in e["loc"]) for e in exc.errors()],
                }
            },
            422,
        )

    @app.exception_handler(BotError)
    async def bot_error(request, exc):
        status = (
            401
            if exc.code == "AUTHENTICATION_FAILED"
            else 503
            if exc.code in {"NETWORK_ERROR", "DATABASE_ERROR"}
            else 409
        )
        return JSONResponse({"detail": {"code": exc.code, "message": str(exc)}}, status)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        await runtime.fail_safe(exc)
        return JSONResponse(
            {"detail": {"code": "INTERNAL_ERROR", "message": "Errore interno: bot sospeso"}}, 500
        )

    @app.get("/bootstrap/{bootstrap_token}")
    async def bootstrap(bootstrap_token: str):
        if not hmac.compare_digest(bootstrap_token, token):
            return JSONResponse(
                {"detail": {"code": "UNAUTHORIZED", "message": "Sessione non valida"}}, 401
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "grid_session", token, httponly=True, samesite="strict", secure=False, path="/"
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/health")
    async def health():
        return {
            "version": __version__,
            "status": "ok",
            "environment": runtime.environment.value,
            "mainnet_allowed": runtime.mainnet_allowed,
        }

    @app.get("/api/state")
    async def state():
        return await runtime.state()

    @app.get("/api/events")
    async def events():
        return await runtime.store.records("strategy_events")

    @app.get("/api/orders")
    async def orders():
        return await runtime.store.orders()

    @app.get("/api/candles")
    async def candles(interval: str = "15"):
        if interval not in {"1", "5", "15", "30", "60", "240", "D"}:
            from .errors import ValidationError

            raise ValidationError("Timeframe non valido")
        return (
            await runtime.adapter.candles(runtime.config.symbol, interval)
            if runtime.adapter
            else []
        )

    @app.post("/api/credentials")
    async def credentials(body: CredentialsInput):
        await runtime.save_credentials(Credentials(**body.model_dump()))
        return {"saved": True}

    @app.post("/api/connect")
    async def connect(body: ConnectInput):
        account = await runtime.connect(body.environment)
        return {"account": account.model_dump(mode="json"), "status": runtime.status}

    @app.post("/api/config")
    async def config(body: StrategyConfig):
        await runtime.configure(body)
        return {"config": runtime.config.model_dump(mode="json")}

    @app.post("/api/start")
    async def start(body: StartInput):
        await runtime.start(body.live_confirm, body.live_ack)
        return {"status": runtime.status}

    @app.post("/api/pause")
    async def pause():
        await runtime.pause()
        return {"status": runtime.status}

    @app.post("/api/recovery")
    async def recovery(body: RecoveryInput):
        return await runtime.inject(body.side, body.confirm)

    @app.post("/api/close-all")
    async def close_all(body: CloseInput):
        await runtime.close_all(body.confirm, body.ack)
        return {"status": runtime.status}

    @app.post("/api/wizard")
    async def wizard(body: WizardInput):
        async with runtime.lock:
            await runtime.store.put(
                "configuration",
                "app",
                {"wizard_completed": body.completed, "session_id": runtime.session_id},
            )
            runtime.wizard_completed = body.completed
            await runtime.notify("wizard_completed", "Configurazione iniziale salvata", {})
        return {"saved": True}

    @app.post("/api/shutdown")
    async def shutdown():
        try:
            await runtime.pause()
        finally:
            if shutdown_callback:
                shutdown_callback()
        return {"status": "SHUTTING_DOWN"}

    @app.websocket("/api/ws")
    async def websocket(ws: WebSocket):
        if (
            ws.headers.get("host") not in allowed_hosts
            or ws.headers.get("origin") not in allowed_origins
        ):
            await ws.close(code=1008)
            return
        await ws.accept()
        if not authorized(ws.headers, ws.cookies):
            try:
                message = await asyncio.wait_for(ws.receive_json(), timeout=3)
                if message.get("type") != "authenticate" or not hmac.compare_digest(
                    str(message.get("token", "")), token
                ):
                    await ws.close(code=1008)
                    return
            except (ValueError, TimeoutError, WebSocketDisconnect):
                await ws.close(code=1008)
                return
        queue = asyncio.Queue(maxsize=100)
        runtime.listeners.add(queue)
        try:
            while True:
                await ws.send_json({"type": "state", "data": await runtime.state()})
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.75)
                    await ws.send_json({"type": "event", "data": event})
                except TimeoutError:
                    continue
        except (WebSocketDisconnect, OSError):
            return
        except Exception as exc:
            await runtime.fail_safe(exc)
            try:
                await ws.close(code=1011)
            except RuntimeError:
                # Socket was closed by peer; state failure was already recorded.
                return
        finally:
            runtime.listeners.discard(queue)

    if frontend_dir and frontend_dir.is_dir():
        root = frontend_dir.resolve()

        @app.get("/{path:path}")
        async def static(path: str):
            candidate = (root / path).resolve()
            if candidate != root and root not in candidate.parents:
                return JSONResponse(
                    {"detail": {"code": "INVALID_PATH", "message": "Percorso non valido"}}, 403
                )
            if candidate.is_file():
                return FileResponse(candidate)
            # SPA routing is intentionally limited; unknown dot files are not served.
            if path not in {"", "home", "activity", "settings"}:
                return JSONResponse(
                    {"detail": {"code": "NOT_FOUND", "message": "Risorsa non trovata"}}, 404
                )
            return FileResponse(root / "index.html")

    return app
