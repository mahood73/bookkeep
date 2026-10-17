"""Hardcover list requests reach the same fulfilment path as UI requests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, tasks
from app.database import Base
from app.downloads.direct.providers.base import DirectSearchResult
from app.routers import downloads, requests


@pytest.fixture
def sync_library(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'hardcover.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([
            models.User(id=1, email='fixture@example.invalid', username='fixture', is_admin=True),
            models.UserHardcoverSync(user_id=1, is_enabled=True, sync_to_read=True, default_format='ebook'),
            models.DirectDownloadSettings(enabled=True, annas_archive_enabled=True, zlibrary_enabled=False),
            models.DownloadClient(name='fixture', type='qbittorrent', protocol='torrent',
                                  host='fixture.invalid', port=8080, enabled=True),
        ])
        db.commit()
    work = {'id': 123, 'title': 'Station Eleven', 'slug': 'station-eleven',
            'contributions': [{'author': {'id': 10, 'name': 'Emily St. John Mandel'}}]}

    async def hardcover(query, variables, token):
        if 'books_by_pk' in query:
            return {'books_by_pk': work}
        if 'list_books' in query:
            return {'list_books': [{'book_id': 123}]}
        return {'me': [{'user_books': [{'book': {'id': 123}}]}]}

    monkeypatch.setattr(tasks, 'SessionLocal', sessions)
    monkeypatch.setattr(tasks, '_hardcover_graphql', hardcover)
    monkeypatch.setattr('app.routers.settings.get_hardcover_token', lambda db: ('fixture-token', False))
    monkeypatch.setattr(tasks.asyncio, 'sleep', AsyncMock())
    prowlarr = Mock(return_value=[])
    direct = AsyncMock(return_value=[DirectSearchResult(
        title='Station Eleven', author='Emily St. John Mandel', language='en',
        format=extension, size_bytes=1024, download_url=f'https://fixture.invalid/md5/{extension}',
        provider='annas_archive', quality_score=80,
    ) for extension in ['epub', 'm4b']])
    monkeypatch.setattr('app.downloads.prowlarr.api.ProwlarrClient.search', prowlarr)
    monkeypatch.setattr('app.downloads.direct.providers.annas_archive.AnnasArchiveProvider.search', direct)
    # Keep real task creation and worker claiming; do not execute the download worker.
    worker = Mock()
    monkeypatch.setattr('app.downloads.orchestrator.threading', SimpleNamespace(Thread=worker))
    yield SimpleNamespace(sessions=sessions, prowlarr=prowlarr, direct=direct, worker=worker)
    engine.dispose()


async def visible_state(library):
    with library.sessions() as db:
        user = db.get(models.User, 1)
        rows = requests.get_requests(skip=0, limit=100, status_filter=None, user_id=None,
                                     db=db, current_user=user)
        request_state = [(row.format, row.status, row.source, row.admin_notes) for row in rows]
        download_state = await downloads.get_download_tasks(db=db, current_user=user)
        return request_state, download_state


@pytest.mark.asyncio
@pytest.mark.parametrize('requested_format', ['ebook', 'audiobook', 'both'])
@pytest.mark.parametrize('origin', ['to_read', 'list', 'both'])
async def test_new_auto_approved_list_request_starts_confident_direct_fallback_once(sync_library, requested_format, origin):
    with sync_library.sessions() as db:
        config = db.query(models.UserHardcoverSync).one()
        config.default_format = requested_format
        config.sync_to_read = origin != 'list'
        config.sync_list_ids = '[7]' if origin != 'to_read' else '[]'
        db.commit()
    await tasks.sync_hardcover_lists_for_user(1)
    rows, download_state = await visible_state(sync_library)
    formats = ['audiobook', 'ebook'] if requested_format == 'both' else [requested_format]
    assert sorted(rows) == [(fmt, 'processing', 'hardcover_sync', None) for fmt in formats]
    assert sorted((task['protocol'], task['format'], task['state']) for task in download_state) == [
        ('direct', fmt, 'processing') for fmt in formats]
    assert sync_library.prowlarr.called
    assert sync_library.direct.await_count == len(formats)
    assert sync_library.worker.return_value.start.call_count == len(formats)
    calls = sync_library.prowlarr.call_count
    await tasks.sync_hardcover_lists_for_user(1)
    assert await visible_state(sync_library) == (rows, download_state)
    assert sync_library.prowlarr.call_count == calls
    assert sync_library.direct.await_count == len(formats)
    assert sync_library.worker.return_value.start.call_count == len(formats)


@pytest.mark.asyncio
@pytest.mark.parametrize('fmt', ['ebook', 'audiobook'])
async def test_requests_requiring_approval_wait_without_searching(sync_library, fmt):
    with sync_library.sessions() as db:
        db.query(models.UserHardcoverSync).one().default_format = fmt
        setattr(db.get(models.User, 1), f'auto_approve_{fmt}s', False)
        db.commit()
    await tasks.sync_hardcover_lists_for_user(1)
    rows, download_state = await visible_state(sync_library)
    assert rows == [(fmt, 'pending', 'hardcover_sync', None)]
    assert download_state == []
    sync_library.prowlarr.assert_not_called()
    sync_library.direct.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('gate', ['permission', 'available', 'approved', 'not_found', 'processing'])
async def test_existing_or_ineligible_books_are_not_automatically_revisited(sync_library, gate):
    with sync_library.sessions() as db:
        book = models.Book(title='Station Eleven', author='Emily St. John Mandel', hardcover_id=123)
        db.add(book)
        db.flush()
        if gate == 'permission':
            db.get(models.User, 1).can_request_ebook = False
        elif gate == 'available':
            book.ebook_available = True
        else:
            db.add(models.BookRequest(book_id=book.id, user_id=1, format='ebook',
                                      status=gate, source='hardcover_sync'))
        db.commit()
    before = await visible_state(sync_library)
    await tasks.sync_hardcover_lists_for_user(1)
    assert await visible_state(sync_library) == before
    sync_library.prowlarr.assert_not_called()
    sync_library.direct.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['prowlarr', 'direct', 'worker'])
async def test_failure_is_visible_and_is_not_retried_by_the_next_sync(sync_library, failure):
    from app.downloads import SearchError
    if failure == 'prowlarr':
        sync_library.prowlarr.side_effect = SearchError('Prowlarr unavailable; retry manually.')
    elif failure == 'direct':
        sync_library.direct.side_effect = SearchError('Direct provider quota exhausted; retry manually.')
    else:
        sync_library.worker.return_value.start.side_effect = RuntimeError('fixture worker unavailable')
    await tasks.sync_hardcover_lists_for_user(1)
    rows, download_state = await visible_state(sync_library)
    assert rows[0][:3] == ('ebook', 'approved', 'hardcover_sync')
    assert 'retry manually' in rows[0][3]
    if failure == 'worker':
        assert [task['state'] for task in download_state] == ['error']
    else:
        assert download_state == []
    calls = (sync_library.prowlarr.call_count, sync_library.direct.await_count)
    await tasks.sync_hardcover_lists_for_user(1)
    assert await visible_state(sync_library) == (rows, download_state)
    assert (sync_library.prowlarr.call_count, sync_library.direct.await_count) == calls
    if failure == 'prowlarr':
        sync_library.direct.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('mismatch', ['title', 'author', 'language', 'empty'])
async def test_unconfident_or_missing_releases_stay_approved(sync_library, mismatch):
    if mismatch == 'empty':
        sync_library.direct.return_value = []
    else:
        for release in sync_library.direct.return_value:
            setattr(release, mismatch, 'different')
    await tasks.sync_hardcover_lists_for_user(1)
    rows, download_state = await visible_state(sync_library)
    assert rows == [('ebook', 'approved', 'hardcover_sync', None)]
    assert download_state == []
    sync_library.worker.assert_not_called()


@pytest.mark.asyncio
async def test_one_failed_format_does_not_abort_other_new_requests(sync_library):
    from app.downloads import SearchError
    with sync_library.sessions() as db:
        db.query(models.UserHardcoverSync).one().default_format = 'both'
        db.commit()
    # Ebook fails at Prowlarr; the subsequent audiobook search is empty and
    # can proceed to the confident direct result without retrying the ebook.
    sync_library.prowlarr.side_effect = [SearchError('Prowlarr unavailable; retry manually.')] + [[]] * 8
    await tasks.sync_hardcover_lists_for_user(1)
    rows, download_state = await visible_state(sync_library)
    by_format = {row[0]: row for row in rows}
    assert by_format['ebook'][1] == 'approved'
    assert 'retry manually' in by_format['ebook'][3]
    assert by_format['audiobook'][1] == 'processing'
    assert [(task['format'], task['protocol']) for task in download_state] == [('audiobook', 'direct')]
