"""Manual job dispatch and its observable schedule/run-status contract."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import models, scheduler, tasks
from app.routers import jobs


@pytest.mark.asyncio
@pytest.mark.parametrize('job_name',['refresh_seed_data','check_processing_requests','sync_from_booklore','sync_from_audiobookshelf','sync_missing_metadata','sync_hardcover_lists'])
async def test_manual_job_runs_once_and_keeps_its_periodic_schedule(sessions,monkeypatch,job_name):
    effects=[]
    async def sync():
        effects.append('synced')
    monkeypatch.setattr(tasks,job_name,sync)
    sched=AsyncIOScheduler(timezone='UTC')
    next_run=datetime.now(timezone.utc)+timedelta(hours=6)
    sched.add_job(sync,IntervalTrigger(hours=6,timezone='UTC'),id=job_name,next_run_time=next_run)
    sched.start(paused=True)
    monkeypatch.setattr(scheduler,'scheduler',sched)
    try:
        with sessions() as db:
            db.add(models.JobSchedule(job_name=job_name,interval_seconds=21600,is_enabled=True))
            db.commit()
            background=BackgroundTasks()
            result=await jobs.run_job(job_name,background,db=db,current_user=SimpleNamespace(id=1))
            assert sched.get_job(job_name).next_run_time==next_run
            await background()
            assert effects==['synced']
            status=await jobs.get_job_status(result['run_id'],current_user=SimpleNamespace(id=1))
            assert status['status']=='completed'
            for stamp in [result['triggered_at'],status['started_at'],status['completed_at']]:
                assert datetime.fromisoformat(stamp.replace('Z','+00:00')).tzinfo==timezone.utc
            assert db.get(models.JobSchedule,1).interval_seconds==21600
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('job_name,status_code',[('unknown_job',404),('sync_download_states',404),('sync_hardcover_lists',500)])
async def test_invalid_dispatch_leaves_schedule_and_run_history_untouched(sessions,monkeypatch,job_name,status_code):
    from fastapi import HTTPException
    monkeypatch.setattr(tasks,'sync_hardcover_lists',None)
    sched=AsyncIOScheduler(timezone='UTC')
    next_run=datetime.now(timezone.utc)+timedelta(hours=6)
    sched.add_job(AsyncMock(),IntervalTrigger(hours=6,timezone='UTC'),id='sync_hardcover_lists',next_run_time=next_run)
    sched.start(paused=True)
    monkeypatch.setattr(scheduler,'scheduler',sched)
    try:
        with sessions() as db:
            db.add(models.JobSchedule(job_name='sync_hardcover_lists',interval_seconds=21600,is_enabled=True))
            db.commit()
            background=BackgroundTasks()
            with pytest.raises(HTTPException) as caught:
                await jobs.run_job(job_name,background,db=db,current_user=SimpleNamespace(id=1))
            assert caught.value.status_code==status_code
            assert background.tasks==[]
            assert sched.get_job('sync_hardcover_lists').next_run_time==next_run
            db.expire_all()
            assert db.get(models.JobSchedule,1).last_execution is None
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_failed_manual_work_is_reported_once_without_retry(sessions,monkeypatch):
    effects=[]
    async def fail():
        effects.append('attempt')
        raise RuntimeError('Fixture work failed')
    monkeypatch.setattr(tasks,'sync_hardcover_lists',fail)
    with sessions() as db:
        db.add(models.JobSchedule(job_name='sync_hardcover_lists',interval_seconds=21600,is_enabled=True))
        db.commit()
        background=BackgroundTasks()
        result=await jobs.run_job('sync_hardcover_lists',background,db=db,current_user=SimpleNamespace(id=1))
        await background()
        status=await jobs.get_job_status(result['run_id'],current_user=SimpleNamespace(id=1))
        assert (effects,status['status'],status['error'])==(['attempt'],'failed','Fixture work failed')
