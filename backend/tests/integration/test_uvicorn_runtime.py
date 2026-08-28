import asyncio
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, WebSocket
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


async def _wait_until_started(server: uvicorn.Server) -> None:
    while not server.started and not server.should_exit:
        await asyncio.sleep(0.01)


@pytest_asyncio.fixture
async def uvicorn_runtime() -> AsyncIterator[tuple[str, uvicorn.Config, asyncio.Event]]:
    shutdown_complete = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        shutdown_complete.set()

    runtime_app = FastAPI(lifespan=lifespan)

    @runtime_app.get("/health")
    async def health():
        return {"status": "ok"}

    @runtime_app.websocket("/ws")
    async def websocket_echo(websocket: WebSocket):
        await websocket.accept()
        if websocket.query_params.get("token") != "valid":
            await websocket.close(code=4401)
            return
        await websocket.send_text(await websocket.receive_text())

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    config = uvicorn.Config(
        runtime_app,
        host="127.0.0.1",
        port=port,
        loop="asyncio",
        ws="auto",
        lifespan="on",
        log_level="error",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))

    try:
        await asyncio.wait_for(_wait_until_started(server), timeout=5)
        assert server.started
        yield f"127.0.0.1:{port}", config, shutdown_complete
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()
        assert shutdown_complete.is_set()


@pytest.mark.asyncio
async def test_uvicorn_auto_websocket_health_and_lifespan(uvicorn_runtime):
    address, config, shutdown_complete = uvicorn_runtime

    async with httpx.AsyncClient(base_url=f"http://{address}") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    with pytest.raises(ConnectionClosed) as exc_info:
        async with connect(f"ws://{address}/ws") as websocket:
            await websocket.recv()
    assert exc_info.value.code == 4401

    async with connect(f"ws://{address}/ws?token=valid") as websocket:
        await websocket.send("ping")
        assert await websocket.recv() == "ping"

    assert config.ws == "auto"
    assert not shutdown_complete.is_set()


def test_uvicorn_startup_failure_exits_with_dedicated_code(tmp_path: Path):
    failing_app = tmp_path / "failing_app.py"
    failing_app.write_text(
        (
            "from contextlib import asynccontextmanager\n"
            "from fastapi import FastAPI\n"
            "\n"
            "@asynccontextmanager\n"
            "async def lifespan(_app):\n"
            "    raise RuntimeError('expected startup failure')\n"
            "    yield\n"
            "\n"
            "app = FastAPI(lifespan=lifespan)"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "failing_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--lifespan",
            "on",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 3
    assert "Application startup failed" in result.stderr


@pytest.mark.asyncio
async def test_proxy_headers_are_honored_only_from_the_configured_nginx_peer():
    observed_clients: list[tuple[str, int] | None] = []

    async def downstream(scope, receive, send):
        observed_clients.append(scope.get("client"))

    middleware = ProxyHeadersMiddleware(
        downstream,
        trusted_hosts="172.30.0.10",
    )

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    base_scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.40")],
    }
    await middleware(
        {**base_scope, "client": ("172.30.0.10", 40000)}, receive, send
    )
    await middleware(
        {**base_scope, "client": ("172.30.0.11", 40001)}, receive, send
    )

    assert observed_clients == [
        ("203.0.113.40", 0),
        ("172.30.0.11", 40001),
    ]


def test_uvicorn_reads_the_exact_proxy_peer_from_its_environment(monkeypatch):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.30.0.10")

    config = uvicorn.Config(lambda _scope, _receive, _send: None)

    assert config.proxy_headers is True
    assert config.forwarded_allow_ips == "172.30.0.10"
