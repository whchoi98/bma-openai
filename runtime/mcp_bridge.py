"""IAM-protected AgentCore HTTP -> local STDIO MCP bridge, alongside the original BMA lifecycle."""
import asyncio
import json
import os
import signal
import sys
import threading
from datetime import timedelta
from http import HTTPStatus
from http.server import ThreadingHTTPServer

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aws_inventory.schema import TOOL_SCHEMAS

MEDIA_TYPE = "application/vnd.seoul-aws.mcp+json"
MAX_REQUEST_BYTES = 65_536
TOOL_TIMEOUT_SECONDS = 90
ENVIRONMENT_NAMES = [
    "APP_REGION", "TARGET_REGION", "EXPECTED_ACCOUNT_ID", "DATA_MODE",
    "MAX_RESOURCES", "MAX_PAGES", "MAX_METRIC_HOURS", "MAX_DATAPOINTS",
    "MODEL_PROCESSING_SCOPE",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
]


def read_bounded_body(handler):
    """Bound allocation for the custom MCP route, including chunked requests."""
    if "chunked" not in handler.headers.get("Transfer-Encoding", "").lower():
        length = int(handler.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError("Invalid request length.")
        body = handler.rfile.read(length)
        if len(body) != length:
            raise ValueError("Incomplete request.")
        return body
    chunks, total = [], 0
    while True:
        line = handler.rfile.readline(128)
        if not line.endswith(b"\r\n"):
            raise ValueError("Invalid chunk length.")
        size = int(line.split(b";")[0], 16)
        if size < 0 or total + size > MAX_REQUEST_BYTES:
            raise ValueError("Request too large.")
        if size == 0:
            trailer_bytes = 0
            while True:
                line = handler.rfile.readline(1024)
                trailer_bytes += len(line)
                if not line.endswith(b"\r\n") or trailer_bytes > 4096:
                    raise ValueError("Invalid trailers.")
                if line == b"\r\n":
                    return b"".join(chunks)
        chunk = handler.rfile.read(size)
        if len(chunk) != size or handler.rfile.read(2) != b"\r\n":
            raise ValueError("Incomplete chunk.")
        chunks.append(chunk)
        total += size


class McpProxy:
    def __init__(self, cwd="/opt/bma", env=None):
        self.cwd = cwd
        self.env = env if env is not None else {k: os.environ[k] for k in ENVIRONMENT_NAMES if k in os.environ}

    async def dispatch(self, request):
        if not isinstance(request, dict):
            raise ValueError("Invalid MCP bridge request.")
        method = request.get("method")
        allowed = {"method"} if method == "tools/list" else {"method", "name", "arguments"}
        if set(request) - allowed or method not in {"tools/list", "tools/call"}:
            raise ValueError("Unsupported MCP bridge operation.")
        if method == "tools/call":
            if request.get("name") not in TOOL_SCHEMAS or not isinstance(request.get("arguments", {}), dict):
                raise ValueError("Unknown tool or invalid arguments.")
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "aws_inventory.mcp_server"],
            cwd=self.cwd, env=self.env,
        )
        async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
            async with stdio_client(params) as (read, write):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=TOOL_TIMEOUT_SECONDS)
                ) as session:
                    await session.initialize()
                    if method == "tools/list":
                        result = await session.list_tools()
                    else:
                        result = await session.call_tool(request["name"], request.get("arguments", {}))
                    return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def serve():
    try:
        from .lifecycle import server as lifecycle
    except ImportError:
        from lifecycle import server as lifecycle

    proxy = McpProxy()
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(4)
    active = 0

    class Handler(lifecycle.Handler):
        def do_GET(self):
            if self.path == "/ping":
                with lock:
                    busy = active > 0
                self.send_json(HTTPStatus.OK, {"status": "HealthyBusy" if busy else lifecycle.LIFECYCLE.health()})
            else:
                super().do_GET()

        def do_POST(self):
            nonlocal active
            if self.headers.get("Content-Type", "").split(";")[0].strip() != MEDIA_TYPE:
                return super().do_POST()
            if self.path != "/invocations":
                self.close_connection = True
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": {"code": "RouteNotFound"}})
            try:
                self.connection.settimeout(15)
                body = read_bounded_body(self)
                request = json.loads(body)
            except (ValueError, TypeError, OSError):
                self.close_connection = True
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"code": "InvalidBridgeRequest"}})
            if not slots.acquire(blocking=False):
                return self.send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": {"code": "McpConcurrencyLimit"}})
            with lock:
                active += 1
            try:
                result = asyncio.run(proxy.dispatch(request))
                self.send_json(HTTPStatus.OK, {"result": result})
            except ValueError:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"code": "InvalidBridgeRequest"}})
            except TimeoutError:
                self.send_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": {"code": "McpToolTimeout"}})
            except Exception as error:
                lifecycle.log("mcp_bridge_failed", error_type=type(error).__name__)
                self.send_json(HTTPStatus.BAD_GATEWAY, {"error": {"code": "McpBridgeFailed"}})
            finally:
                with lock:
                    active -= 1
                slots.release()

    def shutdown(signum, frame):
        lifecycle.LIFECYCLE.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    threading.Thread(target=lifecycle.LIFECYCLE.monitor, daemon=True).start()
    lifecycle.log("server_ready", port=8080, mcp_bridge=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    serve()
