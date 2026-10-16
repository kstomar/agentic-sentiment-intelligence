import httpx
from starlette.datastructures import UploadFile

from tests.helpers import TEST_KEY,SENSITIVE
from tests.integration.test_batch_api import upload,terminal


async def test_characterize_shared_key_job_access_without_tenant_ownership(api):
    """Evidence of missing isolation; does not claim multi-tenant security passes."""
    app,client,_=api
    response=await upload(client,b"review\ncaller-A-data")
    url="/api/v1/batch/jobs/"+response.json()["job_id"];await terminal(client,url)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://second-caller",
                                 headers={"X-API-Key":TEST_KEY})as second:
        response=await second.get(url+"/results")
    assert response.status_code==200
    assert response.json()["results"][0]["evidence_phrases"]==["caller-A-data"]


async def test_validation_errors_and_logs_exclude_rejected_values(api,caplog):
    _,client,_=api
    response=await client.post("/api/v1/sentiment/analyze",json={"text":"x","unexpected":SENSITIVE})
    assert response.status_code==422 and SENSITIVE not in response.text and SENSITIVE not in caplog.text


async def test_spooled_upload_resources_close_on_parse_failure(api,monkeypatch):
    _,client,_=api;closed=[];original=UploadFile.close
    async def close(file):
        await original(file);closed.append(file.file.closed)
    monkeypatch.setattr(UploadFile,"close",close)
    response=await upload(client,b"review\nfine\n"+b"x"*1100000)
    assert response.status_code==422 and closed and all(closed)
