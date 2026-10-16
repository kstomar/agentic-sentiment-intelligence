import importlib
from pathlib import Path
from fastapi.routing import iter_route_contexts

from app.main import create_app
from tests.helpers import settings


EXPECTED={"/health","/api/v1/sentiment/analyze","/api/v1/agent/investigate","/api/v1/chat",
    *["/api/v1/integrations/gmail/"+suffix for suffix in ["connect", "oauth/callback", "status", "disconnect", "import", "imports/{job_id}", "imports/{job_id}/results"]],
    "/api/v1/ingest/feedback", "/api/v1/ingest/events/{delivery_id}", "/api/v1/webhooks/feedback",
    "/api/v1/ingest/events/{delivery_id}/result",
    "/api/v1/batch/upload",*["/api/v1/batch/jobs/{job_id}"+s for s in ["","/report","/results","/download"]]}


def test_openapi_inventory_security_and_response_schemas():
    spec=create_app(settings()).openapi()
    assert set(spec["paths"])==EXPECTED
    for path,methods in spec["paths"].items():
        for operation in methods.values():
            assert "200" in operation["responses"] or "202" in operation["responses"]
            if path!="/health":
                expected_security = ([{"FeedbackHMAC": []}] if path=="/api/v1/webhooks/feedback" else
                                     [{"GmailOAuthState": []}] if path=="/api/v1/integrations/gmail/oauth/callback" else [{"DevelopmentAPIKey":[]}])
                assert operation["security"]==expected_security
                assert "401" in operation["responses"] and "422" in operation["responses"]


def test_all_application_modules_import_and_no_undocumented_routes():
    for path in Path("app").rglob("*.py"):
        name=".".join(path.with_suffix("").parts)
        if name.endswith(".__init__"):name=name[:-9]
        importlib.import_module(name)
    app=create_app(settings())
    # FastAPI 0.162 retains included routers as deferred branches; walk their
    # effective contexts to include hidden routes and applied version prefixes.
    paths={context.path for context in iter_route_contexts(app.routes)}
    assert paths-{ "/docs","/docs/oauth2-redirect","/redoc","/openapi.json"}==EXPECTED
