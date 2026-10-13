"""Bound the entire multipart body before the framework parses or spools it."""

from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import ERROR_MESSAGES, ErrorCode
from app.schemas.errors import ErrorDetail, ErrorResponse


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].rstrip("/") != "/api/v1/batch/upload":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = self.max_body_bytes + 1
        chunks = []
        size = 0
        oversized = declared > self.max_body_bytes
        while not oversized:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_body_bytes:
                oversized = True
                break
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        if oversized:
            code = ErrorCode.BATCH_FILE_TOO_LARGE
            request_id = scope.get("state", {}).get("request_id", uuid4().hex)
            response = ErrorResponse(error=ErrorDetail(code=code, message=ERROR_MESSAGES[code]), request_id=request_id)
            await JSONResponse(
                response.model_dump(mode="json", exclude_none=True), status_code=413, headers={"Connection": "close"}
            )(scope, receive, send)
            return
        body = b"".join(chunks)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
