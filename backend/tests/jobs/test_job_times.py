"""Job API timestamps represent the same instant in BST, GMT and DB fallback."""
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import models, scheduler
from app.routers import jobs


@pytest.mark.asyncio
@pytest.mark.parametrize('month,expected',[(1,'2026-01-17T17:05:00Z'),(10,'2026-10-17T16:05:00Z')])
async def test_job_api_preserves_the_scheduled_instant(sessions,monkeypatch,month,expected):
    actual=datetime(2026,month,17,17,5,tzinfo=ZoneInfo('Europe/London'))
    sched=AsyncIOScheduler(timezone='UTC')
    sched.add_job(AsyncMock(),IntervalTrigger(seconds=300,timezone='Europe/London'),id='sync_hardcover_lists',next_run_time=actual)
    sched.start(paused=True)
    monkeypatch.setattr(scheduler,'scheduler',sched)
    try:
        with sessions() as db:
            db.add(models.JobSchedule(job_name='sync_hardcover_lists',interval_seconds=300,is_enabled=True))
            db.commit()
            assert jobs.get_job_info('sync_hardcover_lists',db)['next_execution']==expected
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('writer',['update_next_execution_in_db','update_job_in_db'])
async def test_saved_schedule_preserves_the_instant_when_scheduler_is_unavailable(sessions,monkeypatch,writer):
    sched=AsyncIOScheduler(timezone='UTC')
    actual=datetime(2026,10,17,17,5,tzinfo=ZoneInfo('Europe/London'))
    sched.add_job(AsyncMock(),IntervalTrigger(seconds=300,timezone='Europe/London'),id='sync_hardcover_lists',next_run_time=actual)
    sched.start(paused=True)
    monkeypatch.setattr(scheduler,'scheduler',sched)
    try:
        with sessions() as db:
            db.add(models.JobSchedule(job_name='sync_hardcover_lists',interval_seconds=300,is_enabled=True))
            db.commit()
        getattr(scheduler,writer)('sync_hardcover_lists')
        monkeypatch.setattr(scheduler,'scheduler',AsyncIOScheduler(timezone='UTC'))
        with sessions() as db:
            assert jobs.get_job_info('sync_hardcover_lists',db)['next_execution']=='2026-10-17T16:05:00Z'
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_rescheduled_job_keeps_utc_in_saved_fallback(sessions,monkeypatch):
    from datetime import timezone
    from functools import partial
    import apscheduler.schedulers.base as scheduler_base
    import apscheduler.triggers.interval as interval_module
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            fixed=datetime(2026,10,17,16,0,tzinfo=timezone.utc)
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
    monkeypatch.setattr(scheduler_base,'datetime',FrozenDateTime)
    monkeypatch.setattr(interval_module,'datetime',FrozenDateTime)
    monkeypatch.setattr(scheduler,'IntervalTrigger',partial(IntervalTrigger,timezone='Europe/London'))
    sched=AsyncIOScheduler(timezone='UTC')
    sched.add_job(AsyncMock(),IntervalTrigger(seconds=300,timezone='Europe/London'),id='sync_hardcover_lists',next_run_time=datetime(2026,10,17,17,5,tzinfo=ZoneInfo('Europe/London')))
    sched.start(paused=True)
    monkeypatch.setattr(scheduler,'scheduler',sched)
    try:
        with sessions() as db:
            db.add(models.JobSchedule(job_name='sync_hardcover_lists',interval_seconds=300,is_enabled=True))
            db.commit()
        scheduler.reschedule_job('sync_hardcover_lists',600)
        monkeypatch.setattr(scheduler,'scheduler',AsyncIOScheduler(timezone='UTC'))
        with sessions() as db:
            result=jobs.get_job_info('sync_hardcover_lists',db)
            assert result['next_execution']=='2026-10-17T16:10:00Z'
            assert result['interval_seconds']==600
    finally:
        sched.shutdown(wait=False)
