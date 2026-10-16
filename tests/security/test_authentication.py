import httpx
import pytest

from app.main import create_app
from tests.helpers import settings,TEST_KEY


PROTECTED=[("POST","/api/v1/sentiment/analyze"),("POST","/api/v1/agent/investigate"),
    ("POST","/api/v1/chat"),("POST","/api/v1/batch/upload"),
    *[("GET","/api/v1/batch/jobs/"+"0"*32+suffix)for suffix in ["","/report","/results","/download"]]]


@pytest.mark.parametrize("method,path",PROTECTED)
@pytest.mark.parametrize("key",[None,"incorrect-key"])
async def test_every_protected_route_rejects_credentials(api,method,path,key):
    _,client,h=api
    headers={} if key is None else {"X-API-Key":key}
    request=client.build_request(method,path,headers=headers)
    if key is None:request.headers.pop("X-API-Key",None)
    response=await client.send(request)
    assert response.status_code==401 and response.json()["error"]["code"]=="AUTHENTICATION_FAILED"
    assert not h.model.calls and not h.selector.calls


async def test_health_public_and_missing_application_configuration(services):
    config=settings().model_copy(update={"app_api_key":None})
    app=create_app(config,sentiment_service=services.sentiment,investigation_service=services.investigation)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url="http://local") as client:
            assert (await client.get("/health")).status_code==200
            response=await client.post("/api/v1/sentiment/analyze",headers={"X-API-Key":TEST_KEY},json={"text":"x"})
            assert response.status_code==503 and response.json()["error"]["code"]=="APP_AUTH_NOT_CONFIGURED"
