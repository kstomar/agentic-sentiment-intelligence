import json

from app.core.upload_limits import UploadSizeLimitMiddleware


async def test_chunked_multipart_body_guard_runs_before_parser():
    called=False;messages=[]
    incoming=iter([{"type":"http.request","body":b"1234","more_body":True},
                   {"type":"http.request","body":b"5678","more_body":False}])
    async def downstream(*args):
        nonlocal called;called=True
    async def receive():return next(incoming)
    async def send(message):messages.append(message)
    await UploadSizeLimitMiddleware(downstream,7)({"type":"http","path":"/api/v1/batch/upload","headers":[],"state":{}},receive,send)
    assert not called and messages[0]["status"]==413


async def test_characterize_missing_json_body_byte_limit(api):
    """A passing characterization of a security gap, not body-limit compliance."""
    _,client,h=api
    body=json.dumps({"text":"bounded text"}).encode()+b" "*(2*1024**2+1)
    response=await client.post("/api/v1/sentiment/analyze",content=body,headers={"Content-Type":"application/json"})
    assert response.status_code==200 and len(h.model.calls)==1


async def test_malicious_filename_never_used_as_storage_path(api,tmp_path):
    _,client,_=api
    name=str(tmp_path/"should-not-exist.csv")
    response=await client.post("/api/v1/batch/upload",data={"text_column":"review"},files={"file":(name,b"review\nfine","text/csv")})
    assert response.status_code==202 and not (tmp_path/"should-not-exist.csv").exists()
