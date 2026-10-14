"""Thin business-owned Gmail endpoints; callback authority is single-use OAuth state."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Security
from fastapi.security import APIKeyQuery

from app.core.exceptions import ApplicationError, ErrorCode
from app.core.security import require_permission
from app.core.tenant_auth import Permission, Principal
from app.integrations.google_gmail import ISSUER
from app.schemas.errors import ErrorResponse
from app.schemas.gmail import (
    GmailAccepted, GmailConnect, GmailConnectionStatus, GmailDisconnected,
    GmailImportRequest, GmailJobStatus, GmailOAuthComplete, GmailResults,
)

router = APIRouter(prefix='/integrations/gmail', tags=['gmail'], responses={
    code: {'model': ErrorResponse} for code in [400, 401, 403, 404, 408, 409, 413, 422, 429, 500, 502, 503, 504]
})
ConnectPrincipal = Annotated[Principal, Depends(require_permission(Permission.GMAIL_CONNECT))]
ReadPrincipal = Annotated[Principal, Depends(require_permission(Permission.GMAIL_READ))]
ImportPrincipal = Annotated[Principal, Depends(require_permission(Permission.GMAIL_IMPORT))]
JobPath = Annotated[str, Path(pattern=r'^[0-9a-f]{32}$')]
oauth_state = APIKeyQuery(name='state', scheme_name='GmailOAuthState', auto_error=False,
                         description='Single-use, expiring authorization state issued to an authenticated business. No X-API-Key on this callback.')


@router.post('/connect', response_model=GmailConnect)
async def connect(request: Request, principal: ConnectPrincipal) -> GmailConnect:
    return request.app.state.gmail_service.connect(principal)


@router.get('/oauth/callback', response_model=GmailOAuthComplete, openapi_extra={
    'parameters': [{'name': name, 'in': 'query', 'required': False, 'schema': {'type': 'string', 'maxLength': 2048}}
                   for name in ['code', 'error', 'scope']] + [
        {'name': 'iss', 'in': 'query', 'required': False,
         'schema': {'type': 'string', 'enum': [ISSUER]},
         'description': 'When supplied, must exactly match the Google authorization-server issuer.'}],
})
async def callback(request: Request, state: Annotated[str | None, Security(oauth_state)] = None) -> GmailOAuthComplete:
    allowed = {'state', 'code', 'error', 'error_description', 'error_uri', 'scope', 'authuser', 'prompt', 'hd', 'iss'}
    params = request.query_params
    if (set(params) - allowed or any(len(params.getlist(key)) != 1 for key in params)
        or (('code' in params) == ('error' in params))
        or ('iss' in params and params['iss'] != ISSUER)
        or any(len(value) > 2048 for key, value in params.items() if key != 'state')):
        raise ApplicationError(ErrorCode.VALIDATION_ERROR)
    await request.app.state.gmail_service.callback(state, params.get('code'), params.get('error'))
    return GmailOAuthComplete()


@router.get('/status', response_model=GmailConnectionStatus)
async def connection_status(request: Request, principal: ReadPrincipal) -> GmailConnectionStatus:
    return request.app.state.gmail_service.status(principal)


@router.delete('/disconnect', response_model=GmailDisconnected)
async def disconnect(request: Request, principal: ConnectPrincipal) -> GmailDisconnected:
    return await request.app.state.gmail_service.disconnect(principal)


@router.post('/import', response_model=GmailAccepted, status_code=202)
async def import_feedback(payload: GmailImportRequest, request: Request, principal: ImportPrincipal) -> GmailAccepted:
    return request.app.state.gmail_service.submit(payload, principal)


@router.get('/imports/{job_id}', response_model=GmailJobStatus)
async def import_status(job_id: JobPath, request: Request, principal: ReadPrincipal) -> GmailJobStatus:
    return request.app.state.gmail_service.job_status(job_id, principal)


@router.get('/imports/{job_id}/results', response_model=GmailResults)
async def import_results(job_id: JobPath, request: Request, principal: ReadPrincipal) -> GmailResults:
    return request.app.state.gmail_service.results(job_id, principal)
