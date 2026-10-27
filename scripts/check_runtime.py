#!/usr/bin/env python3
"""Probe the built container with networking disabled: MCP, user, binary, skills and /ping."""
import asyncio
import json
import subprocess
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

IMAGE = "bma-seoul-runtime:0.1.0"


async def mcp_probe():
    params = StdioServerParameters(
        command="docker", args=["run", "--rm", "--network", "none", "-i", "-e", "DATA_MODE=sample",
                               IMAGE, "/opt/bma/venv/bin/python", "-m", "aws_inventory.mcp_server"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("list_ec2_instances", {})
            body = json.loads(result.content[0].text)
            assert len(tools.tools) == 24 and body["mode"] == "sample" and body["count"] == 2
            return {"mcp_tools": len(tools.tools), "mcp_sample_call": "passed"}


def runtime_probe():
    code = r'''
import json,os,subprocess,time,urllib.request
from pathlib import Path
assert os.getuid()==1000
assert os.environ["AWS_REGION"]=="us-east-1"
assert subprocess.check_output(["/opt/bma/bin/codex","--version"],text=True).strip()=="codex-cli 0.164.0"
skills=sorted(p.parent.name for p in Path("/opt/bma/skills").glob("*/SKILL.md"))
assert len(skills)==4
process=subprocess.Popen(["/opt/bma/venv/bin/python","/opt/bma/mcp_bridge.py"],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
    for attempt in range(50):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/ping",timeout=1) as response:
                health=json.load(response)
            break
        except OSError:time.sleep(.1)
    else:raise RuntimeError("lifecycle server did not start")
    assert health["status"]=="Healthy"
    def invoke(body,media):
        request=urllib.request.Request("http://127.0.0.1:8080/invocations",data=json.dumps(body).encode(),headers={"Content-Type":media})
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    original=invoke({"action":"status"},"application/json")
    assert original["execServerRunning"] is False
    bridge=invoke({"method":"tools/call","name":"get_account_context","arguments":{}},"application/vnd.seoul-aws.mcp+json")
    assert bridge["result"]["structuredContent"]["mode"]=="sample"
    assert bridge["result"]["structuredContent"]["account_id"]=="000000000000"
    print(json.dumps({"uid":os.getuid(),"codex_version":"0.164.0","skills":skills,"health":health["status"],"network":"none","bma_lifecycle":"passed","http_stdio_mcp_bridge":"passed"}))
finally:
    process.terminate()
    process.wait(timeout=5)
'''
    raw = subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "-i", "-e", "DATA_MODE=sample",
         IMAGE, "/opt/bma/venv/bin/python", "-"],
        input=code, text=True, timeout=30,
    )
    return json.loads(raw)


if __name__ == "__main__":
    result = {"image": IMAGE, **runtime_probe(), **asyncio.run(mcp_probe())}
    Path("artifacts/runtime-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
