"""Bounded mocked measurements; no assertions about production inference speed."""

import asyncio
import math
import statistics
import time

import pytest
from mcp import Client

from app.mcp_server.server import create_mcp_server
from app.schemas.batch import JobState,UploadOptions
from app.services.file_parser import FileParser
from app.services.reporting_service import ReportingService
from app.storage.job_store import JobStore
from app.tools.batch_analysis import analyze_record
from tests.helpers import settings,xlsx


def record(measurements,name,samples):
    ordered=sorted(samples)
    measurements.append({"name":name,"samples":len(samples),"concurrency":1,"median_ms":round(statistics.median(samples),4),
        "p95_ms":round(ordered[math.ceil(.95*len(ordered))-1],4),"max_ms":round(max(samples),4),"errors":0,"provider":"mocked"})


@pytest.mark.benchmark
async def test_http_latency_samples(api,measurements):
    _,client,_=api
    scenarios=[("health","GET","/health",None,30),("validation","POST","/api/v1/sentiment/analyze",{},30),
        ("mock_sentiment","POST","/api/v1/sentiment/analyze",{"text":"sample"},30),
        ("mock_investigation","POST","/api/v1/agent/investigate",{"question":"q","feedback":[{"id":"A","text":"sample"}]},20)]
    for name,method,path,payload,count in scenarios:
        samples=[]
        for _ in range(count):
            start=time.perf_counter();response=await client.request(method,path,json=payload)
            samples.append((time.perf_counter()-start)*1000)
            assert response.status_code==(422 if name=="validation" else 200)
        record(measurements,name,samples)


@pytest.mark.benchmark
async def test_parser_and_reducer_samples(services,measurements):
    parser=FileParser(max_bytes=2*1024**2,max_records=100,max_text=5000,max_extracted=16*1024**2)
    options=UploadOptions(text_column="review")
    csv=b"review\n"+b"sample\n"*100
    excel=xlsx([["review"],*[["sample"]for _ in range(100)]])
    for name,data in [("csv_100",csv),("xlsx_100",excel)]:
        samples=[]
        for _ in range(20):
            start=time.perf_counter();parsed=parser.parse(data,"safe."+("csv"if name=="csv_100"else"xlsx"),"application/octet-stream",options)
            samples.append((time.perf_counter()-start)*1000);assert len(parsed.records)==100
        record(measurements,name,samples)
    parsed=parser.parse(csv,"safe.csv","text/csv",options)
    job=JobStore(30).add(options,parsed.records,0);job.status=JobState.RUNNING
    job.results=[await analyze_record(r,"general",services.sentiment)for r in parsed.records]
    samples=[]
    for _ in range(20):
        start=time.perf_counter();report=ReportingService().build(job,JobState.COMPLETED)
        samples.append((time.perf_counter()-start)*1000);assert report.successful_records==100
    record(measurements,"aggregation_100",samples)


@pytest.mark.benchmark
async def test_mcp_invocation_samples(services,measurements):
    server=create_mcp_server(settings(),sentiment_service=services.sentiment,investigation_service=services.investigation)
    samples=[]
    async with Client(server,mode="legacy",cache=None)as client:
        await client.list_tools()
        for _ in range(30):
            start=time.perf_counter();result=await client.call_tool("analyze_feedback",{"text":"sample"})
            samples.append((time.perf_counter()-start)*1000);assert not result.is_error
    record(measurements,"mcp_inprocess_mock_sentiment",samples)
