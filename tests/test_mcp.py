import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def test_stdio_negotiation_discovery_and_query_are_real():
    async def run():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "aws_inventory.mcp_server"],
            cwd=str(ROOT),
            env={"DATA_MODE": "sample", "PYTHONPATH": str(ROOT)},
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                names = {tool.name for tool in listing.tools}
                assert len(names) == 24
                assert {"get_account_context", "list_ec2_instances", "get_resource_metrics"} <= names
                assert all(tool.annotations.readOnlyHint for tool in listing.tools)
                account = await session.call_tool("get_account_context", {})
                body = json.loads(account.content[0].text)
                assert body["mode"] == "sample"
                assert body["account_id"] == "000000000000"
                assert body["status"] == "ok"
                result = await session.call_tool("list_ec2_instances", {})
                body = json.loads(result.content[0].text)
                assert body["count"] == 2
                assert body["api_calls"][-1]["api"] == "DescribeInstances"
                invalid = await session.call_tool("list_ec2_instances", {"account_id": "999988887777"})
                assert invalid.isError
                unknown = await session.call_tool("execute_aws_cli", {"command": "aws ec2 stop-instances"})
                assert unknown.isError

    asyncio.run(run())
