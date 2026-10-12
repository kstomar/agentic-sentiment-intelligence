import asyncio
import sys
from pathlib import Path

import mcp_types
import pytest
from mcp import Client
import mcp.client.stdio as stdio
from mcp.client.stdio import StdioServerParameters

from app.core.exceptions import ApplicationError,ErrorCode as E
from app.mcp_server.server import create_mcp_server
from app.schemas.investigation import InvestigationResponse
from app.schemas.sentiment import SentimentResponse
from tests.helpers import Model,SENSITIVE,harness,settings,until


@pytest.mark.protocol
@pytest.mark.parametrize("mode",["legacy","auto"])
async def test_real_inprocess_protocol_workflows_g_h(services,mode):
    server=create_mcp_server(settings(),sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with Client(server,mode=mode,cache=None)as client:
        tools={t.name:t for t in (await client.list_tools()).tools}
        assert set(tools)=={"analyze_feedback","investigate_feedback"}
        a,b=tools["analyze_feedback"],tools["investigate_feedback"]
        assert a.input_schema["properties"]["text"]["maxLength"]==5000
        assert b.input_schema["properties"]["feedback"]["maxItems"]==10
        assert a.output_schema==SentimentResponse.model_json_schema()
        assert b.output_schema==InvestigationResponse.model_json_schema()
        assert (await client.list_resources()).resources==[] and (await client.list_prompts()).prompts==[]
        result=await client.call_tool("analyze_feedback",{"text":"MCP-only"})
        assert not result.is_error and result.structured_content["evidence_phrases"]==["MCP-only"]
        result=await client.call_tool("investigate_feedback",{"question":"Main issues?","feedback":[{"id":"A","text":"first"},{"id":"B","text":"second"}]})
        parsed=InvestigationResponse.model_validate(result.structured_content)
        assert parsed.total_feedback==2 and parsed.top_issues[0].feedback_ids==["A","B"]
    assert [c["text"]for c in services.model.calls]==["MCP-only","first","second"]
    assert len(services.selector.calls)==1


@pytest.mark.protocol
@pytest.mark.parametrize("name,args",[
    ("analyze_feedback",{"text":" ","secret":SENSITIVE}),
    ("analyze_feedback",{"text":"x"*5001}),
    ("analyze_feedback",{"text":"x","source":"file_upload"}),
    ("investigate_feedback",{"question":"q","feedback":[]}),
    ("investigate_feedback",{"question":"q","feedback":[{"id":"A","text":"x"}]*2}),
    ("investigate_feedback",{"question":"q","feedback":"[]"}),
    ("get_batch_report",{"job_id":SENSITIVE}),
    ("run_shell",{"command":SENSITIVE}),
])
async def test_mcp_rejects_invalid_arguments_and_unapproved_capabilities(services,name,args):
    server=create_mcp_server(settings(),sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with Client(server,mode="legacy",cache=None)as client:
        result=await client.call_tool(name,args)
        assert result.is_error and result.structured_content is None
        assert "VALIDATION_ERROR" in result.content[0].text and SENSITIVE not in str(result)
    assert not services.model.calls and not services.selector.calls


@pytest.mark.protocol
@pytest.mark.parametrize("code",[E.UPSTREAM_TIMEOUT,E.UPSTREAM_AUTHENTICATION_FAILED,E.UPSTREAM_RATE_LIMITED,E.EVIDENCE_VERIFICATION_FAILED])
async def test_mcp_preserves_service_errors(services,code):
    services.model.errors["error"]=ApplicationError(code)
    server=create_mcp_server(settings(),sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with Client(server,mode="legacy",cache=None)as client:
        result=await client.call_tool("analyze_feedback",{"text":"error"})
    assert result.is_error and code.value in result.content[0].text and result.structured_content is None


@pytest.mark.protocol
async def test_mcp_missing_config_and_unexpected_error_sanitization(caplog):
    for service,expected in [(None,"GROQ_NOT_CONFIGURED"),(harness(model=Model(errors={SENSITIVE:RuntimeError(SENSITIVE)})).sentiment,"INTERNAL_ERROR")]:
        server=create_mcp_server(settings(),sentiment_service=service)
        async with Client(server,mode="legacy",cache=None)as client:
            result=await client.call_tool("analyze_feedback",{"text":SENSITIVE})
        assert result.is_error and expected in result.content[0].text
        assert SENSITIVE not in str(result) and SENSITIVE not in caplog.text


@pytest.mark.protocol
async def test_mcp_capacity_cancellation_and_recovery():
    gate=asyncio.Event();h=harness(model=Model(gate=gate))
    server=create_mcp_server(settings(mcp_max_concurrent_calls=1),sentiment_service=h.sentiment,investigation_service=h.investigation)
    async with Client(server,mode="legacy",cache=None)as client:
        task=asyncio.create_task(client.call_tool("analyze_feedback",{"text":"first"}))
        await until(lambda:server._active_calls==1)
        busy=await client.call_tool("analyze_feedback",{"text":"second"})
        assert busy.is_error and "MCP_BUSY" in busy.content[0].text
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        await until(lambda:server._active_calls==0)
        gate.set()
        assert not (await client.call_tool("analyze_feedback",{"text":"third"})).is_error
    assert server._active_calls==0


@pytest.mark.protocol
@pytest.mark.parametrize("mocked",[True,False])
async def test_stdio_official_client_protocol_only_stdout_and_clean_shutdown(monkeypatch,tmp_path,mocked):
    buffers=[];processes=[];original=stdio._create_platform_compatible_process
    class Capture:
        def __init__(self,inner,buffer):self.inner=inner;self.buffer=buffer
        async def receive(self,max_bytes=65536):
            data=await self.inner.receive(max_bytes);self.buffer.extend(data);return data
        async def aclose(self):await self.inner.aclose()
    class Proxy:
        def __init__(self,inner,buffer):self.inner=inner;self.stdout=Capture(inner.stdout,buffer)
        def __getattr__(self,name):return getattr(self.inner,name)
    async def spawn(**kwargs):
        process=await original(**kwargs);buffer=bytearray();buffers.append(buffer);processes.append(process);return Proxy(process,buffer)
    monkeypatch.setattr(stdio,"_create_platform_compatible_process",spawn)
    params=StdioServerParameters(command=sys.executable,args=["-B","-m","tests.stdio_bootstrap" if mocked else "app.mcp_server.server"],
        cwd=str(Path(__file__).resolve().parents[2]),env={"GROQ_API_KEY":"","APP_API_KEY":"","LOG_LEVEL":"DEBUG","LANGSMITH_TRACING":"false"})
    async with asyncio.timeout(30):
        with (tmp_path/"stderr.txt").open("w+")as errlog:
            async with Client(stdio.stdio_client(params,errlog=errlog),mode="legacy",cache=None,read_timeout_seconds=15)as client:
                assert {t.name for t in (await client.list_tools()).tools}=={"analyze_feedback","investigate_feedback"}
                for name,args in [("analyze_feedback",{"text":SENSITIVE}),("investigate_feedback",{"question":"q","feedback":[{"id":"A","text":SENSITIVE}]})]:
                    result=await client.call_tool(name,args)
                    assert result.is_error is (not mocked)
                    if not mocked:assert "GROQ_NOT_CONFIGURED" in result.content[0].text
            errlog.seek(0);stderr=errlog.read()
    assert processes[0].returncode==0
    lines=bytes(buffers[0]).splitlines()
    assert len(lines)>=4
    for line in lines:mcp_types.jsonrpc_message_adapter.validate_json(line,by_name=False)
    assert SENSITIVE not in stderr and "Traceback" not in stderr
