import asyncio

import pytest

from app.schemas.batch import BatchDownload, BatchReport
from tests.helpers import until,xlsx


async def upload(client,content,name="safe.csv",mime="text/csv",fields=None):
    return await client.post("/api/v1/batch/upload",data=fields or {"text_column":"review"},files={"file":(name,content,mime)})


async def terminal(client,url):
    async with asyncio.timeout(3):
        while True:
            response=await client.get(url)
            if response.json()["status"] in ["COMPLETED","PARTIAL_SUCCESS","FAILED"]:return response
            await asyncio.sleep(.002)


@pytest.mark.parametrize("extension",["csv","xlsx"])
async def test_upload_report_download_workflows_e_f(api,extension):
    _,client,h=api
    if extension=="csv":content=b"id,review,date\nA,first,2024-01-02\nB,,bad\n"
    else:content=xlsx([["id","review","date"],["A","first","2024-01-02"],["B",None,"bad"]])
    response=await upload(client,content,"safe."+extension,"application/octet-stream",{"text_column":"review","id_column":"id","date_column":"date"})
    assert response.status_code==202 and response.json()["status"]=="PENDING"
    url="/api/v1/batch/jobs/"+response.json()["job_id"]
    status=await terminal(client,url)
    assert status.json()["status"]=="PARTIAL_SUCCESS"
    report=BatchReport.model_validate((await client.get(url+"/report")).json())
    assert report.successful_records==1 and report.failed_records==1 and report.invalid_date_records==1
    response=await client.get(url+"/download");download=BatchDownload.model_validate(response.json())
    assert download.report==report and len(download.results)==2
    assert response.headers["Cache-Control"]=="no-store" and response.headers["X-Content-Type-Options"]=="nosniff"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="batch-')
    page=(await client.get(url+"/results?page=2&page_size=1")).json()
    assert page["results"][0]["feedback_id"]=="B" and page["results"][0]["status"]=="FAILED"
    assert (await client.get(url+"/results?page=20")).json()["results"]==[]
    assert len(h.model.calls)==1


async def test_pending_running_reports_and_concurrent_status_reads(api):
    _,client,h=api;h.model.gate=asyncio.Event()
    response=await upload(client,b"review\nwait")
    url="/api/v1/batch/jobs/"+response.json()["job_id"]
    await until(lambda:h.model.active==1)
    assert (await client.get(url+"/report")).status_code==202
    assert (await client.get(url+"/download")).status_code==202
    statuses=await asyncio.gather(*(client.get(url)for _ in range(8)))
    assert all(r.json()["processed_records"]==0 and r.json()["status"]=="RUNNING"for r in statuses)
    h.model.gate.set();assert (await terminal(client,url)).json()["status"]=="COMPLETED"


@pytest.mark.parametrize("content,name,mime,fields,status",[
    (b"review\na","safe.xls","application/octet-stream",None,415),
    (b"review\na","safe.csv","application/json",None,415),
    (b"review\n\xff","safe.csv","text/csv",None,422),
    (b"other\na","safe.csv","text/csv",None,422),
    (b"review\na","safe.csv","text/csv",{"text_column":"review","id_column":""},422),
    (b"review\na","safe.csv","text/csv",{"text_column":"review","extra":"x"},422),
    (b"review\n"+b"a\n"*101,"safe.csv","text/csv",None,422),
    (b"x"*(2*1024**2+1),"safe.csv","text/csv",None,413),
    (b"x"*(2*1024**2+65537),"safe.csv","text/csv",None,413),
])
async def test_upload_rejection_without_model_calls(api,content,name,mime,fields,status):
    _,client,h=api
    response=await upload(client,content,name,mime,fields)
    assert response.status_code==status and not h.model.calls


async def test_explicit_blank_source_is_rejected(api):
    """QA finding if FastAPI silently replaces a supplied blank label with default."""
    _,client,_=api
    response=await upload(client,b"review\na",fields={"text_column":"review","source":""})
    assert response.status_code==422, "README and UploadOptions require a nonblank supplied source"


@pytest.mark.parametrize("path",["bad-id","0"*32,"0"*32+"/results?page=0","0"*32+"/results?page_size=101"])
async def test_job_ids_and_pagination_validation(api,path):
    _,client,_=api
    response=await client.get("/api/v1/batch/jobs/"+path)
    assert response.status_code==(404 if path=="0"*32 else 422)


async def test_missing_file(api):
    _,client,_=api
    assert (await client.post("/api/v1/batch/upload",data={"text_column":"review"})).status_code==422


@pytest.mark.parametrize("source,expected", [
    (None, "file_upload"),
    ("file_upload", "file_upload"),
    ("customer_review", "customer_review"),
    ("custom_import", "custom_import"),
    (" external_crm ", "external_crm"),
    ("x" * 64, "x" * 64),
])
async def test_source_default_and_valid_metadata_labels_are_preserved(api, source, expected):
    _, client, h = api
    fields = {"text_column": "review"}
    if source is not None:
        fields["source"] = source
    response = await upload(client, b"review\nsynthetic feedback", fields=fields)
    assert response.status_code == 202
    url = "/api/v1/batch/jobs/" + response.json()["job_id"]
    assert (await terminal(client, url)).json()["status"] == "COMPLETED"
    report = await client.get(url + "/report")
    assert report.status_code == 200 and report.json()["source"] == expected
    # Batch labels remain metadata; T01 retains its existing source contract.
    assert len(h.model.calls) == 1 and h.model.calls[0]["source"] == "manual"


@pytest.mark.parametrize("source", ["   ", "\t\r\n", "x" * 65])
async def test_whitespace_and_overlong_sources_do_not_create_jobs(api, source):
    app, client, h = api
    response = await upload(client, b"review\nsynthetic feedback",
                            fields={"text_column": "review", "source": source})
    assert response.status_code == 422
    assert not h.model.calls and not app.state.batch_service._store.jobs


async def test_nontext_source_form_part_is_rejected(api):
    app, client, h = api
    response = await client.post(
        "/api/v1/batch/upload", data={"text_column": "review"},
        files={"file": ("synthetic.csv", b"review\nsynthetic feedback", "text/csv"),
               "source": ("label.txt", b"unsupported file value", "text/plain")},
    )
    assert response.status_code == 422
    assert not h.model.calls and not app.state.batch_service._store.jobs
