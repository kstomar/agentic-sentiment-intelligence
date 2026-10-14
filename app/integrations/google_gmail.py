"""Small async adapter for fixed Google endpoints, bounded reads and safe failures."""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import ApplicationError, ErrorCode as E

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
ISSUER = 'https://accounts.google.com'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
GMAIL_URL = 'https://gmail.googleapis.com/gmail/v1/users/me'
MESSAGE_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
MAX_LABELS = 10000  # Gmail's documented per-mailbox maximum; byte cap still applies.
Operation = Literal['oauth.exchange', 'oauth.refresh', 'profile.get', 'labels.list', 'messages.list', 'messages.get']
TransportMode = Literal['default', 'injected', 'unspecified']
Stage = Literal['transport', 'response_bytes', 'json', 'response_shape', 'http_status', 'tokens',
                'mailbox_identity', 'label_list', 'label_row', 'label_id', 'label_selection',
                'message_list', 'message_row', 'message_id', 'page_token', 'message_identity', 'message_labels']
logger = logging.getLogger('app.gmail')


def provider_failure(operation: Operation, stage: Stage, code: E = E.GMAIL_RESPONSE_INVALID,
                     status: int | None = None, *, method: str | None = None,
                     host: str | None = None, response_bytes: int | None = None,
                     transport: TransportMode = 'unspecified') -> ApplicationError:
    # All arguments are fixed internal labels/codes or an HTTP status integer.
    # Never pass provider messages, URLs, tokens, identifiers or email data here.
    if method is None:
        logger.warning('gmail_provider_rejected operation=%s stage=%s status=%s code=%s',
                       operation, stage, status, code)
    else:
        # Never echo an arbitrary method/host, header or URL supplied by a custom
        # client/hook. Byte count is measured from the bounded decoded stream,
        # not trusted from a provider's Content-Length header.
        safe_method = method if method in ('GET', 'POST', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'DELETE') else 'OTHER'
        safe_host = host if host in ('gmail.googleapis.com', 'oauth2.googleapis.com') else 'OTHER'
        safe_transport = transport if transport in ('default', 'injected', 'unspecified') else 'unspecified'
        safe_bytes = response_bytes if type(response_bytes) is int and response_bytes >= 0 else None
        logger.warning('gmail_provider_rejected operation=%s stage=%s status=%s code=%s '
                       'method=%s host=%s response_bytes=%s transport=%s',
                       operation, stage, status, code, safe_method, safe_host, safe_bytes, safe_transport)
    return ApplicationError(code)


def _error_reasons(error: object) -> set[str]:
    if not isinstance(error, dict):
        return set()
    reasons: set[str] = set()
    for name in ('errors', 'details'):
        entries = error.get(name)
        if isinstance(entries, list):
            reasons.update(item['reason'] for item in entries
                           if isinstance(item, dict) and isinstance(item.get('reason'), str))
    return reasons


def identifier(value: object) -> str:
    if not isinstance(value, str) or MESSAGE_ID.fullmatch(value) is None:
        raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
    return value


def _token(value: object) -> SecretStr:
    if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
    return SecretStr(value)


@dataclass(repr=False)
class Tokens:
    access: SecretStr | None
    refresh: SecretStr | None
    expires_at: float
    refresh_expires_at: float | None = None

    def clear(self) -> None:
        self.access = self.refresh = None


def parse_tokens(data: dict, *, previous_refresh: SecretStr | None = None,
                 previous_refresh_expiry: float | None = None) -> Tokens:
    if data.get('scope') != SCOPE or not isinstance(data.get('token_type'), str) or data['token_type'].lower() != 'bearer':
        raise ApplicationError(E.GMAIL_SCOPE_INVALID)
    seconds = data.get('expires_in')
    if type(seconds) is not int or not 0 < seconds <= 86400:
        raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
    refresh = _token(data['refresh_token']) if 'refresh_token' in data else previous_refresh
    refresh_expiry = previous_refresh_expiry
    if 'refresh_token_expires_in' in data:
        ttl = data['refresh_token_expires_in']
        if type(ttl) is not int or not 0 < ttl <= 366 * 86400:
            raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
        refresh_expiry = time.monotonic() + ttl
    return Tokens(_token(data.get('access_token')), refresh, time.monotonic() + seconds, refresh_expiry)


def payload_fields(*, data: bool, depth: int = 0) -> str:
    body = 'size,attachmentId' + (',data' if data else '')
    children = payload_fields(data=data, depth=depth + 1) if depth < 4 else 'partId'
    return f'partId,mimeType,filename,headers(name,value),body({body}),parts({children})'


class GoogleGmail:
    """No generic fetch API, redirects, token URLs in queries, or attachment endpoint."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings, *,
                 transport_mode: TransportMode = 'unspecified') -> None:
        self.client = client
        self.settings = settings
        self.active = 0
        self.transport_mode = transport_mode

    async def _request(self, method: str, url: str, *, operation: Operation,
                       token: SecretStr | None = None, params: dict | None = None,
                       data: dict | None = None, retry: bool = True) -> dict:
        if self.active >= self.settings.gmail_http_max_concurrent_calls:
            raise ApplicationError(E.GMAIL_CAPACITY_EXCEEDED)
        self.active += 1
        stage: Stage = 'transport'
        status: int | None = None
        request_method, request_host = method, httpx.URL(url).host
        response_bytes: int | None = None
        try:
            async with asyncio.timeout(self.settings.gmail_http_timeout_seconds):
                attempts = self.settings.gmail_http_max_retries if retry else 0
                for attempt in range(attempts + 1):
                    stage, status = 'transport', None
                    request_method, request_host = method, httpx.URL(url).host
                    response_bytes = None
                    try:
                        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
                        if token is not None:
                            headers['Authorization'] = 'Bearer ' + token.get_secret_value()
                        async with self.client.stream(method, url, headers=headers, params=params, data=data,
                                                      follow_redirects=False) as response:
                            status = response.status_code
                            request_method = response.request.method
                            request_host = response.request.url.host
                            response_bytes = 0
                            content = bytearray()
                            stage = 'response_bytes'
                            async for chunk in response.aiter_bytes(chunk_size=4096):
                                response_bytes += len(chunk)
                                if response_bytes > self.settings.gmail_max_provider_response_bytes:
                                    raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
                                content.extend(chunk)
                            stage = 'json'
                            try:
                                result = json.loads(content)
                            except (ValueError, UnicodeError, RecursionError):
                                if status == 200:
                                    raise ApplicationError(E.GMAIL_RESPONSE_INVALID) from None
                                result = None  # HTTP errors need not have a JSON body.
                            if status == 200:
                                stage = 'response_shape'
                                if not isinstance(result, dict) or 'error' in result:
                                    raise ApplicationError(E.GMAIL_RESPONSE_INVALID)
                                return result
                            stage = 'http_status'
                            error = result.get('error') if isinstance(result, dict) else None
                            if (url == TOKEN_URL and error in ('invalid_grant', 'invalid_token')) or status == 401:
                                raise ApplicationError(E.GMAIL_RECONNECT_REQUIRED)
                            reasons = _error_reasons(error)
                            rate = status == 429 or (status == 403 and bool(reasons & {
                                'rateLimitExceeded', 'userRateLimitExceeded', 'dailyLimitExceeded', 'quotaExceeded'}))
                            if status == 403 and reasons & {'authError', 'insufficientPermissions', 'ACCESS_TOKEN_SCOPE_INSUFFICIENT'}:
                                raise ApplicationError(E.GMAIL_RECONNECT_REQUIRED)
                            transient = rate or status in {500, 502, 503, 504}
                            code = E.GMAIL_RATE_LIMITED if rate else E.GMAIL_PROVIDER_ERROR
                            if not transient or attempt == attempts:
                                raise ApplicationError(code)
                    except httpx.TimeoutException:
                        if attempt == attempts:
                            raise ApplicationError(E.GMAIL_TIMEOUT) from None
                    except httpx.HTTPError:
                        if attempt == attempts:
                            raise ApplicationError(E.GMAIL_PROVIDER_ERROR) from None
                    await asyncio.sleep(.1 * 2**attempt)
        except TimeoutError:
            raise provider_failure(operation, stage, E.GMAIL_TIMEOUT, status,
                method=request_method, host=request_host, response_bytes=response_bytes,
                transport=self.transport_mode) from None
        except ApplicationError as error:
            raise provider_failure(operation, stage, error.code, status,
                method=request_method, host=request_host, response_bytes=response_bytes,
                transport=self.transport_mode) from None
        finally:
            self.active -= 1
        raise ApplicationError(E.GMAIL_PROVIDER_ERROR)

    def _client_data(self) -> dict:
        assert self.settings.google_oauth_client_id and self.settings.google_oauth_client_secret
        return {'client_id': self.settings.google_oauth_client_id.get_secret_value(),
                'client_secret': self.settings.google_oauth_client_secret.get_secret_value()}

    async def exchange(self, code: str, verifier: SecretStr) -> Tokens:
        # Authorization codes are one-use: never retry an ambiguous exchange.
        data = self._client_data() | {'code': code, 'code_verifier': verifier.get_secret_value(),
            'redirect_uri': self.settings.google_oauth_redirect_uri, 'grant_type': 'authorization_code'}
        response = await self._request('POST', TOKEN_URL, operation='oauth.exchange', data=data, retry=False)
        try:
            return parse_tokens(response)
        except ApplicationError as error:
            raise provider_failure('oauth.exchange', 'tokens', error.code, 200) from None

    async def refresh(self, tokens: Tokens) -> Tokens:
        if tokens.refresh is None:
            raise ApplicationError(E.GMAIL_RECONNECT_REQUIRED)
        data = self._client_data() | {'refresh_token': tokens.refresh.get_secret_value(), 'grant_type': 'refresh_token'}
        response = await self._request('POST', TOKEN_URL, operation='oauth.refresh', data=data)
        try:
            return parse_tokens(response, previous_refresh=tokens.refresh,
                                previous_refresh_expiry=tokens.refresh_expires_at)
        except ApplicationError as error:
            raise provider_failure('oauth.refresh', 'tokens', error.code, 200) from None

    async def profile(self, token: SecretStr) -> str:
        data = await self._request('GET', GMAIL_URL + '/profile', operation='profile.get', token=token, params={'fields': 'emailAddress'})
        address = data.get('emailAddress')
        if not isinstance(address, str) or len(address) > 254 or re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", address) is None:
            raise provider_failure('profile.get', 'mailbox_identity', status=200)
        return address.casefold()

    async def label(self, token: SecretStr) -> str:
        data = await self._request('GET', GMAIL_URL + '/labels', operation='labels.list', token=token, params={'fields': 'labels(id,name)'})
        # Google may omit an empty repeated field. No configured label is a
        # selection/configuration error, never permission to scan the mailbox.
        labels = data.get('labels', [])
        if not isinstance(labels, list) or len(labels) > MAX_LABELS:
            raise provider_failure('labels.list', 'label_list', status=200)
        matches = []
        for row in labels:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                raise provider_failure('labels.list', 'label_row', status=200)
            try:
                label_id = identifier(row.get('id'))
            except ApplicationError:
                raise provider_failure('labels.list', 'label_id', status=200) from None
            if row['name'] == self.settings.gmail_feedback_label:
                matches.append(label_id)
        if len(matches) != 1 or matches[0] in {'SPAM', 'TRASH', 'INBOX', 'SENT', 'DRAFT'}:
            raise provider_failure('labels.list', 'label_selection', E.GMAIL_SELECTION_INVALID, 200)
        return matches[0]

    async def list_page(self, token: SecretStr, label: str, maximum: int, page: str | None) -> dict:
        params = {'labelIds': label, 'q': f'newer_than:{self.settings.gmail_search_days}d -in:sent',
                  'includeSpamTrash': 'false', 'maxResults': maximum,
                  'fields': 'messages(id,threadId),nextPageToken'}
        if page is not None:
            params['pageToken'] = page
        return await self._request('GET', GMAIL_URL + '/messages', operation='messages.list', token=token, params=params)

    async def message_labels(self, token: SecretStr, message_id: str) -> list[str]:
        # Minimal format returns only identity/labels, never headers or body.
        data = await self._request('GET', GMAIL_URL + '/messages/' + identifier(message_id),
            operation='messages.get', token=token, params={'format': 'minimal', 'fields': 'id,labelIds'})
        if data.get('id') != message_id:
            raise provider_failure('messages.get', 'message_identity', status=200)
        labels = data.get('labelIds', [])
        if not isinstance(labels, list) or any(not isinstance(label, str) or not 1 <= len(label) <= 128 for label in labels):
            raise provider_failure('messages.get', 'message_labels', status=200)
        return labels

    async def message(self, token: SecretStr, message_id: str, *, body: bool) -> dict:
        fields = 'id,threadId,labelIds,internalDate,payload(' + payload_fields(data=body) + ')'
        return await self._request('GET', GMAIL_URL + '/messages/' + identifier(message_id), operation='messages.get', token=token,
                                   params={'format': 'full', 'fields': fields})
