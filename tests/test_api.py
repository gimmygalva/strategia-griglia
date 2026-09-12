from datetime import datetime, timedelta

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
        client.runtime_fixture = runtime
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


def test_credential_metadata_is_authenticated_write_only_and_environment_scoped(client):
    assert client.get("/api/credentials/status").status_code == 401
    path = "/api/credentials/status"
    assert client.get(path, headers=HEADERS).json()["configured"] is False
    body = {
        "environment": "DEMO",
        "api_key": "metadata-key-only",
        "api_secret": "metadata-secret-only",
    }
    assert client.post("/api/credentials", json=body, headers=HEADERS).json() == {"saved": True}
    response = client.get(path, headers=HEADERS)
    assert response.json() == {
        "environment": "DEMO",
        "configured": True,
        "storage": "Memory only (development)",
    }
    assert body["api_key"] not in response.text and body["api_secret"] not in response.text
    assert client.get(path + "?environment=LIVE", headers=HEADERS).json()["configured"] is False
    assert client.get(path + "?environment=TESTNET", headers=HEADERS).status_code == 422


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


def test_local_ws_audit_has_the_same_durable_identity_and_time_as_rest(client):
    received = []
    with client.websocket_connect("/api/ws", headers={"Origin": "http://testserver"}) as ws:
        ws.send_json({"type": "authenticate", "token": TOKEN})
        assert ws.receive_json()["type"] == "state"
        config = client.get("/api/state", headers=HEADERS).json()["config"]
        for size in ("120", "130"):
            response = client.post(
                "/api/config", json={**config, "order_size_usdt": size}, headers=HEADERS
            )
            assert response.status_code == 200
            for _ in range(8):
                frame = ws.receive_json()
                if frame["type"] == "event":
                    break
            else:
                pytest.fail("Evento audit realtime non ricevuto")
            event = frame["data"]
            durable = next(
                item
                for item in client.get("/api/events", headers=HEADERS).json()
                if item["id"] == event["id"]
            )
            assert event == durable
            assert event["environment"] == "DEMO"
            assert datetime.fromisoformat(event["time"]).utcoffset() == timedelta(0)
            received.append(event)
    assert len({event["id"] for event in received}) == 2


def test_legacy_audit_rows_inherit_the_actual_database_environment(client):
    payload = {"title": "Evento precedente", "event": "legacy", "details": {}}
    client.portal.call(client.runtime_fixture.store.put, "strategy_events", "legacy", payload)
    events = client.get("/api/events", headers=HEADERS).json()
    assert len(events) == 1 and events[0]["environment"] == "DEMO"
    assert events[0]["title"] == payload["title"]


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
