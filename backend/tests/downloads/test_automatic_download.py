"""Automatic fulfilment with fixture sources and a disposable real database."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Book, DirectDownloadSettings, DownloadClient, DownloadTask
from app.downloads import Release
from app.downloads.orchestrator import DownloadOrchestrator


@pytest.fixture
def library(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'library.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr('app.downloads.orchestrator.SessionLocal', sessions)
    with sessions() as db:
        book = Book(title='The Gentleman', author='Forrest Leo', isbn='9780399562655')
        db.add_all([book, DirectDownloadSettings(enabled=True),
                    DownloadClient(name='fixture', type='qbittorrent', port=8080, protocol='torrent', host='fixture.invalid', enabled=True)])
        db.commit()
        yield SimpleNamespace(db=db, book=book, sessions=sessions)
    engine.dispose()


def direct_release(**overrides):
    fields = dict(source='direct', title='The Gentleman', download_url='https://fixture.invalid/book/123/hash',
                  protocol='direct', size_bytes=1024, format='epub', language='en', quality_score=80,
                  metadata={'author':'Forrest Leo'})
    fields.update(overrides)
    return Release(**fields)


def fixture_sources(monkeypatch, prowlarr=(), direct=()):
    sources = {'prowlarr': SimpleNamespace(search=Mock(return_value=list(prowlarr))),
               'direct': SimpleNamespace(search=Mock(return_value=list(direct)))}
    monkeypatch.setattr('app.downloads.orchestrator.get_source', lambda name, **kwargs: sources[name])
    # The background execution boundary is intentionally inert; task creation remains real.
    start = Mock(return_value=True)
    monkeypatch.setattr(DownloadOrchestrator, 'start_download', start)
    return sources, start


def test_empty_prowlarr_search_can_start_a_confident_direct_match(library, monkeypatch):
    fixture_sources(monkeypatch, direct=[direct_release()])
    task = DownloadOrchestrator(library.db).search_and_download(library.book)
    assert task is not None
    assert task.protocol == 'direct'
    assert library.db.query(DownloadTask).count() == 1


def test_source_failure_is_not_an_empty_search_or_permission_to_fallback(library, monkeypatch):
    sources, start = fixture_sources(monkeypatch, direct=[direct_release()])
    sources['prowlarr'].search.side_effect = RuntimeError('private token must not escape')
    with pytest.raises(RuntimeError, match='Prowlarr search failed'):
        DownloadOrchestrator(library.db).search_and_download(library.book)
    assert library.db.query(DownloadTask).count() == 0
    assert not sources['direct'].search.called
    assert not start.called


def test_disabled_direct_sources_are_not_searched(library, monkeypatch):
    library.db.query(DirectDownloadSettings).first().enabled = False
    library.db.commit()
    sources, _ = fixture_sources(monkeypatch, direct=[direct_release()])
    assert DownloadOrchestrator(library.db).search_and_download(library.book) is None
    assert not sources['direct'].search.called


def test_repeat_automatic_request_reuses_a_task_without_starting_it_again(library, monkeypatch):
    _, start = fixture_sources(monkeypatch, direct=[direct_release()])
    first = DownloadOrchestrator(library.db).search_and_download(library.book)
    second = DownloadOrchestrator(library.db).search_and_download(library.book)
    assert first.id == second.id
    assert library.db.query(DownloadTask).count() == 1
    assert start.call_count == 1


def test_overlapping_manual_selection_does_not_create_a_second_task(library):
    first = DownloadOrchestrator(library.db).create_download_task(library.book, direct_release(), 'ebook')
    second = DownloadOrchestrator(library.db).create_download_task(library.book, direct_release(), 'ebook')
    assert first.id == second.id
    assert library.db.query(DownloadTask).count() == 1


@pytest.mark.parametrize('changes', [
    {'title': 'Another Book'}, {'metadata': {'author': 'Another Author'}},
    {'metadata': {}}, {'language': None}, {'language': 'de'},
    {'format': 'mp3'}, {'format': None}, {'title': 'The Gentleman: a sequel'},
])
def test_uncertain_identity_language_or_format_stays_for_manual_selection(library, monkeypatch, changes):
    _, start = fixture_sources(monkeypatch, direct=[direct_release(**changes)])
    assert DownloadOrchestrator(library.db).search_and_download(library.book) is None
    assert not start.called


def test_normalized_identity_is_checked_before_quality_ranking(library, monkeypatch):
    fixture_sources(monkeypatch, direct=[
        direct_release(title='Wrong Book', quality_score=100),
        direct_release(title='  THE Gentleman! ', metadata={'author': 'FORREST   LEO.'}, quality_score=70),
    ])
    task = DownloadOrchestrator(library.db).search_and_download(library.book)
    assert task.release_title == '  THE Gentleman! '


def test_audiobook_request_only_accepts_audio(library, monkeypatch):
    fixture_sources(monkeypatch, direct=[direct_release(), direct_release(format='m4b', quality_score=60)])
    task = DownloadOrchestrator(library.db).search_and_download(library.book, 'audiobook')
    assert task.format == 'audiobook'
    import json
    assert json.loads(task.release_data_json)['format'] == 'm4b'


def test_prowlarr_result_prevents_direct_search(library, monkeypatch):
    sources, _ = fixture_sources(monkeypatch, prowlarr=[direct_release(source='prowlarr', protocol='torrent')], direct=[direct_release()])
    task = DownloadOrchestrator(library.db).search_and_download(library.book)
    assert task.protocol == 'torrent'
    assert not sources['direct'].search.called


@pytest.mark.parametrize('state', ['complete', 'seeding', 'downloading', 'paused'])
def test_existing_fulfilment_is_not_searched_or_started(library, monkeypatch, state):
    task = DownloadOrchestrator(library.db).create_download_task(library.book, direct_release(), 'ebook')
    task.state = state
    library.db.commit()
    sources, start = fixture_sources(monkeypatch, direct=[direct_release()])
    assert DownloadOrchestrator(library.db).search_and_download(library.book).id == task.id
    assert not sources['prowlarr'].search.called and not start.called


def test_available_format_does_not_download_again(library, monkeypatch):
    library.book.ebook_available = True
    library.db.commit()
    sources, start = fixture_sources(monkeypatch, direct=[direct_release()])
    assert DownloadOrchestrator(library.db).search_and_download(library.book) is None
    assert not sources['prowlarr'].search.called and not start.called


def test_concurrent_manual_and_automatic_claims_create_one_task(library):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    book_id = library.book.id
    def claim(automatic):
        with library.sessions() as db:
            book = db.get(Book, book_id)
            barrier.wait(timeout=5)
            return DownloadOrchestrator(db).create_download_task(book, direct_release(), 'ebook', automatic=automatic).id
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, [True, False]))
    assert claims[0] == claims[1]
    assert library.db.query(DownloadTask).count() == 1


def test_only_one_background_worker_can_start_a_task(library, monkeypatch):
    worker = Mock()
    monkeypatch.setattr('app.downloads.orchestrator.threading.Thread', worker)
    task = DownloadOrchestrator(library.db).create_download_task(library.book, direct_release(), 'ebook')
    assert DownloadOrchestrator(library.db).start_download(task.id)
    assert DownloadOrchestrator(library.db).start_download(task.id)
    assert worker.return_value.start.call_count == 1
    assert library.db.get(DownloadTask, task.id).state == 'processing'


def test_failed_selected_download_is_reported_without_fallback(library, monkeypatch):
    from app.models import User, BookRequest
    user = User(email='fixture@example.invalid', username='fixture')
    library.db.add(user)
    library.db.flush()
    request = BookRequest(book_id=library.book.id, user_id=user.id, format='ebook', status='approved')
    library.db.add(request)
    library.db.commit()
    sources, start = fixture_sources(monkeypatch, prowlarr=[direct_release(source='prowlarr', protocol='torrent')])
    start.return_value = False
    with pytest.raises(RuntimeError, match='Selected download could not start'):
        DownloadOrchestrator(library.db).search_and_download(library.book)
    assert not sources['direct'].search.called
    assert 'retry manually' in request.admin_notes


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['single', 'series', 'approval', 'retry'])
async def test_automatic_entry_points_share_fallback_and_real_task_creation(library, monkeypatch, entry):
    from app import schemas
    from app.models import User, BookRequest, AppSettings
    from app.routers import requests, downloads
    user = User(email='fixture@example.invalid', username='fixture', is_admin=True,
                can_request_ebook=True, auto_approve_ebooks=True)
    library.db.add_all([user, AppSettings(key='ebook_download_path', value='/tmp/fixture-staging')])
    library.book.series_id = 1
    library.book.series_position = 1
    library.db.commit()
    sources, start = fixture_sources(monkeypatch, direct=[direct_release()])
    if entry == 'single':
        result = await requests.create_request(schemas.BookRequestCreate(book_id=library.book.id, format='ebook'), library.db, user)
        assert result.status == 'processing'
    elif entry == 'series':
        result = await requests.request_series(1, 'ebook', False, library.db, user)
        assert result['requested_count'] == 1
        assert library.db.query(BookRequest).one().status == 'processing'
    elif entry == 'approval':
        request = BookRequest(book_id=library.book.id, user_id=user.id, format='ebook', status='pending')
        library.db.add(request)
        library.db.commit()
        result = await requests.update_request(request.id, schemas.BookRequestUpdate(status='approved'), library.db, user)
        assert result.status == 'processing'
    else:
        result = await downloads.auto_download(library.book.id, 'ebook', db=library.db, current_user=user)
        assert result.task_id
    assert sources['prowlarr'].search.called
    assert sources['direct'].search.called
    assert library.db.query(DownloadTask).one().protocol == 'direct'
    assert start.call_count == 1


def test_automatic_direct_failure_does_not_try_another_download_source(library, monkeypatch, tmp_path):
    import json
    from contextlib import nullcontext
    from threading import Event
    from app.downloads.handlers.direct import DirectHandler, DownloadSource
    handler = DirectHandler(db_session=library.db)
    task = DownloadOrchestrator(library.db).create_download_task(library.book, direct_release(), 'ebook')
    data = json.loads(task.release_data_json)
    data['metadata']['automatic_selection'] = True
    task.release_data_json = json.dumps(data)
    task.download_url = 'https://fixture.invalid/md5/123'
    monkeypatch.setattr(handler, '_get_download_path', lambda _: tmp_path)
    monkeypatch.setattr(handler, '_create_client', lambda: nullcontext(Mock()))
    monkeypatch.setattr(handler, '_parse_annas_archive_sources', Mock(return_value=[
        DownloadSource('https://fixture.invalid/one', 'one', 'libgen', 1),
        DownloadSource('https://fixture.invalid/two', 'two', 'libgen', 2),
    ]))
    attempt = Mock(return_value=None)
    monkeypatch.setattr(handler, '_try_download_from_source', attempt)
    monkeypatch.setattr('app.downloads.handlers.direct.time.sleep', Mock())
    assert handler.download(task, Event()) is None
    assert attempt.call_count == 1


def test_worker_source_resolution_does_not_reopen_the_queued_claim(library, monkeypatch):
    from threading import Event
    from app.downloads import DownloadState, DownloadStatus
    worker = Mock()
    monkeypatch.setattr('app.downloads.orchestrator.threading.Thread', worker)
    task = DownloadOrchestrator(library.db).create_download_task(library.book, direct_release(), 'ebook')
    handler = Mock()
    def download(**kwargs):
        kwargs['status_callback'](DownloadStatus(DownloadState.QUEUED, 0, message='Finding sources'))
        assert DownloadOrchestrator(library.db).start_download(task.id)
        return None
    handler.download.side_effect = download
    monkeypatch.setattr('app.downloads.orchestrator.get_handler', lambda _: lambda **kwargs: handler)
    DownloadOrchestrator(library.db)._execute_download(task.id, Event())
    assert worker.return_value.start.call_count == 0
    library.db.expire_all()
    assert library.db.get(DownloadTask, task.id).state == 'error'


def test_direct_factory_uses_configured_enabled_providers(library):
    from app.downloads import get_source
    settings = library.db.query(DirectDownloadSettings).one()
    settings.annas_archive_enabled = True
    settings.zlibrary_enabled = False
    library.db.commit()
    source = get_source('direct', db_session=library.db)
    assert [provider.name for provider in source._providers] == ['annas_archive']


def test_manual_search_keeps_uncertain_results(library, monkeypatch):
    fixture_sources(monkeypatch, direct=[direct_release(title='Uncertain title', metadata={})])
    releases = DownloadOrchestrator(library.db).search_releases(library.book, source_name='direct')
    assert [release.title for release in releases] == ['Uncertain title']


@pytest.mark.asyncio
async def test_retry_reports_source_failure_with_safe_http_result(library, monkeypatch):
    from fastapi import HTTPException
    from app.models import AppSettings
    from app.routers import downloads
    library.db.add(AppSettings(key='ebook_download_path', value='/tmp/fixture-staging'))
    library.db.commit()
    sources, _ = fixture_sources(monkeypatch)
    sources['prowlarr'].search.side_effect = RuntimeError('private response')
    with pytest.raises(HTTPException) as caught:
        await downloads.auto_download(library.book.id, 'ebook', db=library.db, current_user=Mock())
    assert caught.value.status_code == 502
    assert caught.value.detail == 'Prowlarr search failed; retry manually.'
