import asyncio
import io
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.mcp_bridge import McpProxy, read_bounded_body

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_bridge_executes_real_stdio_mcp():
    async def run():
        proxy = McpProxy(cwd=str(ROOT), env={"DATA_MODE": "sample"})
        tools = await proxy.dispatch({"method": "tools/list"})
        assert len(tools["tools"]) == 24
        result = await proxy.dispatch({"method": "tools/call", "name": "get_account_context", "arguments": {}})
        assert result["structuredContent"]["account_id"] == "000000000000"
        assert result["structuredContent"]["status"] == "ok"
        assert result["structuredContent"]["mode"] == "sample"
    asyncio.run(run())


@pytest.mark.parametrize("packet", [
    {"method": "execute_aws_cli", "command": "anything"},
    {"method": "tools/call", "name": "execute_aws_cli", "arguments": {}},
    {"method": "tools/list", "region": "us-east-1"},
    {"method": "tools/call", "name": "list_ec2_instances", "arguments": {}, "role_arn": "other"},
])
def test_runtime_bridge_exposes_only_registered_mcp_operations(packet):
    with pytest.raises(ValueError):
        asyncio.run(McpProxy(cwd=str(ROOT), env={"DATA_MODE": "sample"}).dispatch(packet))


@pytest.mark.parametrize("headers,body", [
    ({"Content-Length": "65537"}, b""),
    ({"Content-Length": "-1"}, b""),
    ({"Content-Length": "3"}, b"{}"),
    ({"Transfer-Encoding": "chunked"}, b"10001\r\n"),
    ({"Transfer-Encoding": "chunked"}, b"3\r\n{}\r\n0\r\n\r\n"),
])
def test_bridge_rejects_oversized_or_incomplete_body(headers, body):
    with pytest.raises(ValueError):
        read_bounded_body(SimpleNamespace(headers=headers, rfile=io.BytesIO(body)))


def test_bridge_reads_bounded_chunked_body():
    handler = SimpleNamespace(headers={"Transfer-Encoding": "chunked"},
                              rfile=io.BytesIO(b"1\r\n{\r\n1\r\n}\r\n0\r\n\r\n"))
    assert read_bounded_body(handler) == b"{}"


def test_mcp_deadline_exits_stdio_context(monkeypatch):
    cleaned = []

    @asynccontextmanager
    async def stalled_stdio(params):
        try:
            await asyncio.Event().wait()
            yield None
        finally:
            cleaned.append(True)

    monkeypatch.setattr("runtime.mcp_bridge.TOOL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("runtime.mcp_bridge.stdio_client", stalled_stdio)
    with pytest.raises(TimeoutError):
        asyncio.run(McpProxy().dispatch({"method": "tools/list"}))
    assert cleaned == [True]
