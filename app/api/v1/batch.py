"""Thin multipart, polling, and JSON download adapters for temporary batch jobs."""

import asyncio
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile
from pydantic import ValidationError

from app.core.security import require_api_key, require_permission
from app.core.tenant_auth import Permission, Principal
from app.core.exceptions import ApplicationError, ErrorCode
from app.schemas.batch import BatchDownload, BatchReport, JobAccepted, JobStatus, ResultsPage, UploadOptions
from app.schemas.errors import ErrorResponse
from app.schemas.sentiment import BusinessType
from app.services.batch_service import BatchService

router = APIRouter(
    prefix="/batch", tags=["batch"], dependencies=[Depends(require_api_key)],
    responses={code: {"model": ErrorResponse} for code in [401, 403, 404, 408, 413, 415, 422, 429, 500, 502, 503, 504]},
)
JobPath = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


def get_batch_service(request: Request) -> BatchService:
    return cast(BatchService, request.app.state.batch_service)


@router.post("/upload", response_model=JobAccepted, status_code=202, summary="Upload feedback for background analysis")
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    text_column: Annotated[str, Form(min_length=1, max_length=128)],
    service: Annotated[BatchService, Depends(get_batch_service)],
    principal: Annotated[Principal, Depends(require_permission(Permission.BATCH_CREATE))],
    id_column: Annotated[str | None, Form(max_length=128)] = None,
    date_column: Annotated[str | None, Form(max_length=128)] = None,
    business_type: Annotated[BusinessType, Form()] = "general",
    source: Annotated[str, Form(min_length=1, max_length=64)] = "file_upload",
) -> JobAccepted:
    try:
        form = await request.form()
        allowed = {"file", "text_column", "id_column", "date_column", "business_type", "source"}
        if set(form) - allowed or any(len(form.getlist(key)) != 1 for key in form):
            raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
        # Empty optional Form values receive defaults before this handler runs.
        # Check supplied raw parts so an explicit blank source cannot disappear.
        if any(key in form and isinstance(form[key], str) and not form[key].strip() for key in ["id_column", "date_column", "source"]):
            raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS)
        try:
            options = UploadOptions(
                text_column=text_column, id_column=id_column, date_column=date_column,
                business_type=business_type, source=source,
            )
        except ValidationError:
            raise ApplicationError(ErrorCode.BATCH_INVALID_COLUMNS) from None
        maximum = request.app.state.settings.batch_max_upload_bytes
        if file.size is not None and file.size > maximum:
            raise ApplicationError(ErrorCode.BATCH_FILE_TOO_LARGE)
        data = await file.read(maximum + 1)
        return await service.submit(data, file.filename or "", file.content_type or "application/octet-stream", options, principal=principal)
    finally:
        await file.close()


@router.get("/jobs/{job_id}", response_model=JobStatus, summary="Get batch progress")
async def status(job_id: JobPath, service: Annotated[BatchService, Depends(get_batch_service)],
                 principal: Annotated[Principal, Depends(require_permission(Permission.BATCH_READ))]) -> JobStatus:
    return await asyncio.to_thread(service.status,job_id,principal=principal)


@router.get("/jobs/{job_id}/report", response_model=BatchReport | JobStatus,
            responses={202: {"model": JobStatus}}, summary="Get a completed JSON report")
async def report(
    job_id: JobPath, response: Response, service: Annotated[BatchService, Depends(get_batch_service)],
    principal: Annotated[Principal, Depends(require_permission(Permission.BATCH_READ))]
) -> BatchReport | JobStatus:
    result = await asyncio.to_thread(service.report,job_id,principal=principal)
    if not isinstance(result, BatchReport):
        response.status_code = 202
    return result


@router.get("/jobs/{job_id}/results", response_model=ResultsPage, summary="Page through settled record results")
async def results(
    job_id: JobPath, service: Annotated[BatchService, Depends(get_batch_service)],
    principal: Annotated[Principal, Depends(require_permission(Permission.BATCH_READ))],
    page: Annotated[int, Query(ge=1, le=1000000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ResultsPage:
    return await asyncio.to_thread(service.results,job_id,page=page,page_size=page_size,principal=principal)


@router.get("/jobs/{job_id}/download", response_model=BatchDownload | JobStatus,
            responses={202: {"model": JobStatus}}, summary="Download completed report and results as JSON")
async def download(
    job_id: JobPath, response: Response, service: Annotated[BatchService, Depends(get_batch_service)],
    principal: Annotated[Principal, Depends(require_permission(Permission.BATCH_READ))]
) -> BatchDownload | JobStatus:
    result = await asyncio.to_thread(service.download,job_id,principal=principal)
    if isinstance(result, BatchDownload):
        response.headers["Content-Disposition"] = f'attachment; filename="batch-{job_id}.json"'
    else:
        response.status_code = 202
    return result
