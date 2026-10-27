"""Official MCP SDK, STDIO transport, for BMA's environment-local MCP connection."""
import json
import logging

import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from .config import Settings
from .engine import AwsInventory
from .schema import TOOL_SCHEMAS


def create_server(inventory: AwsInventory) -> Server:
    server = Server("seoul-aws-inventory", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                annotations=ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
                ),
            )
            for name, (_, model, description) in TOOL_SCHEMAS.items()
        ]

    # The engine validates inputs and returns the same metadata for validation failures.
    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        result = await anyio.to_thread.run_sync(inventory.invoke, name, arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False, allow_nan=False))],
            structuredContent=result,
            isError=result["status"] in {
                "invalid_input", "account_mismatch", "access_denied", "unsupported_service", "api_error"
            },
        )

    return server


async def serve():
    server = create_server(AwsInventory(Settings.from_env()))
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    logging.basicConfig(level=logging.WARNING)  # stderr only; stdout is exclusively MCP JSON-RPC.
    anyio.run(serve)


if __name__ == "__main__":
    main()
