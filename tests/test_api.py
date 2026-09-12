import pytest
from fastapi.testclient import TestClient
from gridbot.api import create_app
from gridbot.credentials import MemoryCredentialsStore
from gridbot.runtime import BotRuntime
from starlette.websockets import WebSocketDisconnect

TOKEN = "local-test-token-with-adequate-entropy"
HEADERS = {"Authorization": "Bearer " + TOKEN, "Origin": "http://testserver"}


@pytest.fixture
def client(tmp_path):
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<html><body>Real frontend fixture</body></html>")
    runtime = BotRuntime(
        tmp_path / "data", credentials_store=MemoryCredentialsStore(), mainnet_allowed=False
    )
    app = create_app(runtime, TOKEN, 1234, static, test_origin="http://testserver")
    with TestClient(app) as client:
        yield client


def test_local_api_protected_disconnected_no_fake_values(client):
    assert client.get("/api/health").status_code == 401
    r = client.get("/api/state", headers=HEADERS)
    assert r.status_code == 200
    state = r.json()
    assert state["environment"] == "DEMO"
    assert state["status"] == "DISCONNECTED"
    assert state["price"] is None
    assert state["account"] is None
    assert set(state["portfolio"].values()) == {None}
    assert state["mainnet_allowed"] is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/start",
        "/api/pause",
        "/api/credentials",
        "/api/config",
        "/api/close-all",
        "/api/recovery",
    ],
)
def test_unauthenticated_mutations_rejected(client, path):
    assert client.post(path, json={}).status_code == 401


def test_credentials_write_only_redacted_invalid_input(client):
    body = {"environment": "DEMO", "api_key": "test-only-key", "api_secret": "test-only-secret"}
    assert client.post("/api/credentials", json=body, headers=HEADERS).json() == {"saved": True}
    exported = (
        client.get("/api/state", headers=HEADERS).text
        + client.get("/api/events", headers=HEADERS).text
    )
    assert body["api_key"] not in exported
    assert body["api_secret"] not in exported
    body["environment"] = "TESTNET"
    response = client.post("/api/credentials", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert body["api_secret"] not in response.text
    assert body["api_key"] not in response.text


def test_origin_host_csrf_controls(client):
    assert (
        client.post(
            "/api/pause",
            json={},
            headers={"Authorization": "Bearer " + TOKEN, "Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert client.get("/api/health", headers={**HEADERS, "Host": "evil.test"}).status_code == 403
    response = client.get("/bootstrap/" + TOKEN, follow_redirects=False)
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.post("/api/pause", json={}).status_code == 403
    assert (
        client.post("/api/pause", json={}, headers={"Origin": "http://testserver"}).status_code
        == 200
    )


def test_security_headers_and_path_traversal(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/%2e%2e/settings.json").status_code in {403, 404}
    assert client.get("/api/credentials", headers=HEADERS).status_code in {404, 405}
    assert client.get("/docs").status_code == 404


def test_config_validation_empty_and_existing_persistence(client):
    before = client.get("/api/state", headers=HEADERS).json()["config"]
    body = {**before, "symbol": "BTCUSDT; touch /tmp/pwned"}
    assert client.post("/api/config", json=body, headers=HEADERS).status_code == 422
    body = {**before, "order_size_usdt": "NaN"}
    assert client.post("/api/config", json=body, headers=HEADERS).status_code == 422
    body = {**before, "order_size_usdt": "120"}
    assert client.post("/api/config", json=body, headers=HEADERS).status_code == 200
    assert client.get("/api/state", headers=HEADERS).json()["config"]["order_size_usdt"] == "120"
    assert client.post("/api/start", json={}, headers=HEADERS).status_code == 409
    assert client.get("/api/orders", headers=HEADERS).json() == []


def test_local_ws_auth_and_state(client):
    with client.websocket_connect("/api/ws", headers={"Origin": "http://testserver"}) as ws:
        ws.send_json({"type": "authenticate", "token": TOKEN})
        frame = ws.receive_json()
        assert frame["type"] == "state"
        assert frame["data"]["price"] is None
        assert frame["data"]["environment"] == "DEMO"


def test_ws_wrong_token_and_origin_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"Origin": "http://testserver"}) as ws:
            ws.send_json({"type": "authenticate", "token": "wrong-token"})
            ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"Origin": "https://evil.test"}) as ws:
            ws.receive_json()


def test_close_and_recovery_require_confirmation(client):
    assert (
        client.post(
            "/api/close-all", json={"confirm": "", "ack": False}, headers=HEADERS
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/recovery", json={"side": "LONG", "confirm": False}, headers=HEADERS
        ).status_code
        == 409
    )
    assert client.get("/api/orders", headers=HEADERS).json() == []
