"""Real TLS handshakes prove trust, hostname checks and no pre-auth data leakage."""

import asyncio
import ssl
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import certifi
import httpx
import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from gridbot.errors import ValidationError
from gridbot.tls import verified_context
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve


@pytest.fixture(autouse=True)
def isolated_tls_cache():
    verified_context.cache_clear()
    try:
        yield
    finally:
        verified_context.cache_clear()


@pytest_asyncio.fixture
async def tls_server(tmp_path, protocol):
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Local TLS fixture CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (tmp_path / name for name in ("ca.pem", "cert.pem", "key.pem"))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    application_data = []
    if protocol == "REST":

        async def handler(reader, writer):
            application_data.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=context)
        scheme = "https"
    else:

        async def handler(socket):
            application_data.append(socket.request.headers.get("X-TLS-Probe"))
            await socket.recv()
            await socket.send("OK")

        server = await serve(handler, "127.0.0.1", 0, ssl=context, close_timeout=1)
        scheme = "wss"
    port = server.sockets[0].getsockname()[1]
    try:
        yield SimpleNamespace(
            url=f"{scheme}://localhost:{port}",
            wrong_hostname_url=f"{scheme}://127.0.0.1:{port}",
            ca=ca_path,
            application_data=application_data,
        )
    finally:
        server.close()
        await server.wait_closed()


async def round_trip(protocol, url):
    if protocol == "REST":
        async with httpx.AsyncClient(
            verify=verified_context(), trust_env=False, timeout=2
        ) as client:
            assert (await client.get(url, headers={"X-TLS-Probe": "test-only-auth"})).text == "OK"
    else:
        async with connect(
            url,
            ssl=verified_context(),
            proxy=None,
            additional_headers={"X-TLS-Probe": "test-only-auth"},
            open_timeout=2,
            close_timeout=1,
        ) as socket:
            await socket.send("test-only-message")
            assert await socket.recv() == "OK"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["REST", "WEBSOCKET"])
async def test_untrusted_tls_never_receives_application_auth(protocol, tls_server):
    with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError)):
        await round_trip(protocol, tls_server.url)
    assert tls_server.application_data == []


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["REST", "WEBSOCKET"])
async def test_trusted_tls_uses_shared_ca_bundle(protocol, tls_server, monkeypatch):
    monkeypatch.setattr(certifi, "where", lambda: str(tls_server.ca))
    context = verified_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    await round_trip(protocol, tls_server.url)
    assert len(tls_server.application_data) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["REST", "WEBSOCKET"])
async def test_trusted_ca_still_rejects_wrong_hostname(protocol, tls_server, monkeypatch):
    monkeypatch.setattr(certifi, "where", lambda: str(tls_server.ca))
    with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError), match="certificate"):
        await round_trip(protocol, tls_server.wrong_hostname_url)
    assert tls_server.application_data == []


def test_missing_tls_roots_block_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "missing.pem"))
    with pytest.raises(ValidationError, match="TLS"):
        verified_context()


def test_empty_tls_roots_block_startup(tmp_path, monkeypatch):
    empty = tmp_path / "empty.pem"
    empty.write_text("")
    monkeypatch.setattr(certifi, "where", lambda: str(empty))
    with pytest.raises(ValidationError, match="TLS"):
        verified_context()


def test_frozen_process_refuses_external_ca_dependency(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(ValidationError, match="non incorporato"):
        verified_context()
