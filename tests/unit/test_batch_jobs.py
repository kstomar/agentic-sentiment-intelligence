import asyncio
import threading

import pytest

from app.core.exceptions import ApplicationError, ErrorCode as E
from app.schemas.batch import BatchReport, JobStatus, UploadOptions
from app.services.batch_service import BatchService
from app.storage.job_store import JobStore
from tests.helpers import Model, harness, settings, settled, until


async def submit(manager, data=b"review\nfine"):
    return await manager.submit(data, "safe.csv", "text/csv", UploadOptions(text_column="review"))


async def test_cross_job_limits_progress_and_no_task_fanout():
    gate=asyncio.Event();model=Model(gate=gate);manager=BatchService(harness(model=model).sentiment,settings(batch_max_retained_jobs=3),store=JobStore(1800))
    await manager.start()
    try:
        jobs=[await submit(manager,b"review\na\nb") for _ in range(3)]
        await until(lambda:model.active==2)
        assert model.peak==2 and len(manager._tasks)==3
        with pytest.raises(ApplicationError) as caught: await submit(manager)
        assert caught.value.code==E.BATCH_CAPACITY_EXCEEDED
        status=manager.status(jobs[0].job_id)
        assert status.status=="RUNNING" and status.processed_records==0
        assert isinstance(manager.report(jobs[0].job_id),JobStatus)
        gate.set()
        await asyncio.gather(*(settled(manager,j.job_id)for j in jobs))
        assert model.peak==2 and len(model.calls)==6
        assert all(manager.status(j.job_id).status=="COMPLETED"for j in jobs)
        with pytest.raises(ApplicationError):await submit(manager)  # retained capacity stays occupied
    finally:await manager.close()
    assert not manager._store.jobs and not manager._tasks


async def test_partial_success_counts_and_raw_text_cleanup():
    model=Model(errors={"bad":ApplicationError(E.UPSTREAM_RATE_LIMITED)})
    manager=BatchService(harness(model=model).sentiment,settings(),store=JobStore(1800))
    try:
        accepted=await submit(manager,b"review,extra\ngood,x\nbad,x\n,x")
        record=manager._store.get(accepted.job_id).records[0]
        await settled(manager,accepted.job_id)
        report=manager.report(accepted.job_id)
        assert isinstance(report,BatchReport) and report.status=="PARTIAL_SUCCESS"
        assert (report.total_records,report.valid_records,report.invalid_records,report.successful_records,report.failed_records)==(3,2,1,1,2)
        assert report.attempted_records==2 and report.progress_percentage==100
        assert sum(report.sentiment_percentages.values())==100
        assert record.text is None and manager._store.get(accepted.job_id).records==[]
        assert [r["text"]for r in model.calls]==["good","bad"]
    finally:await manager.close()


@pytest.mark.parametrize("code",[E.UPSTREAM_AUTHENTICATION_FAILED,E.GROQ_NOT_CONFIGURED,E.GROQ_MODEL_UNSUPPORTED])
async def test_fatal_provider_errors_stop_and_latch(code):
    model=Model(errors={"bad":ApplicationError(code)});manager=BatchService(harness(model=model).sentiment,settings(),store=JobStore(1800))
    try:
        job=await submit(manager,b"review\nbad\nnever\nnever2")
        await settled(manager,job.job_id)
        report=manager.report(job.job_id)
        assert report.status=="FAILED" and report.error_code==code and len(model.calls)==1
        assert report.attempted_records==1 and report.unattempted_valid_records==2
        assert all(v==0 for v in report.sentiment_percentages.values())
        with pytest.raises(ApplicationError) as caught:await submit(manager)
        assert caught.value.code==code
    finally:await manager.close()


async def test_whole_job_deadline_accounts_for_cancelled_attempt():
    manager=BatchService(harness(model=Model(gate=asyncio.Event())).sentiment,settings(batch_job_timeout_seconds=.03),store=JobStore(1800))
    try:
        job=await submit(manager,b"review\na\nb");await settled(manager,job.job_id)
        report=manager.report(job.job_id)
        assert report.status=="FAILED" and report.error_code==E.BATCH_JOB_TIMEOUT
        assert report.attempted_records==report.unattempted_valid_records==1
        assert [r.attempted for r in manager.results(job.job_id).results]==[True,False]
    finally:await manager.close()


async def test_lazy_expiry_removes_raw_and_derived_results():
    clock=[0.];store=JobStore(5,clock=lambda:clock[0]);manager=BatchService(harness().sentiment,settings(),store=store)
    try:
        job=await submit(manager);await settled(manager,job.job_id);held=store.get(job.job_id)
        clock[0]=5
        with pytest.raises(ApplicationError) as caught:manager.status(job.job_id)
        assert caught.value.code==E.BATCH_JOB_NOT_FOUND
        assert held.records==[] and held.results==[] and held.report is None
    finally:await manager.close()


async def test_periodic_expiry_and_shutdown_clear():
    manager=BatchService(harness().sentiment,settings(batch_job_ttl_seconds=.02),store=JobStore(.02));await manager.start()
    job=await submit(manager);await settled(manager,job.job_id);await until(lambda:not manager._store.jobs)
    await manager.close()
    model=Model(gate=asyncio.Event());manager=BatchService(harness(model=model).sentiment,settings(),store=JobStore(1800));await manager.start()
    job=await submit(manager);held=manager._store.get(job.job_id);await until(lambda:model.active==1)
    await manager.close()
    assert not manager._store.jobs and held.records==[] and held.results==[] and model.active==0


async def test_cancelled_http_parse_keeps_capacity_until_thread_finishes(monkeypatch):
    manager=BatchService(harness().sentiment,settings(batch_max_active_jobs=1),store=JobStore(1800))
    started=threading.Event();release=threading.Event();captured=[];original=manager._parser.parse
    def parse(*args):
        started.set();release.wait(2);result=original(*args);captured.append(result);return result
    monkeypatch.setattr(manager._parser,"parse",parse)
    task=asyncio.create_task(submit(manager))
    try:
        await until(started.is_set);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert manager._reservations==1
        with pytest.raises(ApplicationError):await submit(manager)
        release.set();await until(lambda:manager._reservations==0)
        assert captured[0].records==[] and not manager._store.jobs
    finally:release.set();await manager.close()


async def test_report_verification_failure_never_publishes_success():
    class Broken:
        def build(self,*args):raise ValueError("fabricated-report-fault")
    manager=BatchService(harness().sentiment,settings(),reporter=Broken(),store=JobStore(1800))
    try:
        job=await submit(manager);await settled(manager,job.job_id)
        assert manager.status(job.job_id).status=="FAILED"
        assert manager.results(job.job_id).results[0].sentiment is None
        with pytest.raises(ApplicationError) as caught:manager.report(job.job_id)
        assert caught.value.code==E.BATCH_REPORT_UNAVAILABLE
    finally:await manager.close()
