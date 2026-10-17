"""Source contracts for automatic searches, using HTTP fixtures only."""
import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import requests

from app.downloads import SearchError
from app.downloads.direct.providers.base import DirectSearchResult
from app.downloads.direct.providers.zlibrary import ZLibraryProvider
from app.downloads.direct.providers.annas_archive import AnnasArchiveProvider
from app.downloads.direct.source import DirectDownloadSource
from app.downloads.prowlarr.api import ProwlarrClient


@pytest.mark.parametrize('failure', ['timeout', 'http', 'invalid'])
def test_prowlarr_failure_stops_before_category_retry_and_is_safe(failure):
    client = ProwlarrClient('http://fixture.invalid', 'fixture-key')
    response = Mock()
    response.status_code = 429
    response.json.return_value = {'error': 'private response'}
    client.session.get = Mock(return_value=response)
    if failure == 'timeout':
        client.session.get.side_effect = requests.Timeout('private response')
    elif failure == 'http':
        response.raise_for_status.side_effect = requests.HTTPError('private response', response=response)
    with pytest.raises(SearchError) as caught:
        client.search_with_retry('Book', categories=[7000], strict=True)
    assert 'private' not in str(caught.value)
    assert 'retry manually' in str(caught.value)
    assert client.session.get.call_count == 1


def test_successful_empty_prowlarr_search_still_checks_without_categories():
    client = ProwlarrClient('http://fixture.invalid', 'fixture-key')
    response = Mock()
    response.json.return_value = []
    client.session.get = Mock(return_value=response)
    assert client.search_with_retry('Book', categories=[7000], strict=True) == []
    assert client.session.get.call_count == 2


@pytest.mark.parametrize('payload', [
    {'success': 0, 'error': 'private quota body'},
    {'success': 1},
    {'success': 1, 'books': {'error': 'private quota body'}},
])
def test_zlibrary_failure_is_not_an_empty_result(payload):
    seen = []
    def respond(request):
        seen.append(request)
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'success': 1, 'user': {'id': 1, 'remix_userkey': 'fixture-session'}})
        return httpx.Response(200, json=payload)
    async def run():
        provider = ZLibraryProvider(email='fixture@example.invalid', password='fixture-password', domain='fixture.invalid')
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with pytest.raises(SearchError) as caught:
                await provider.search('Book', 'Author', strict=True)
            assert 'private' not in str(caught.value)
            assert 'Retry manually' in str(caught.value)
        finally:
            await provider.close()
    asyncio.run(run())
    assert len(seen) == 2


def test_zlibrary_empty_search_is_success_and_manual_error_remains_empty():
    async def run():
        provider = ZLibraryProvider(domain='fixture.invalid')
        provider._authenticate = AsyncMock(return_value=True)
        provider._request = AsyncMock(return_value={'success': 1, 'books': []})
        assert await provider.search('Book', strict=True) == []
        # SearchError contract is supplied by _request's sanitized ZLibraryError.
        from app.downloads.direct.providers.zlibrary import ZLibraryError
        provider._request.side_effect = ZLibraryError('Z-Library API request failed (HTTP 429)')
        assert await provider.search('Book') == []
    asyncio.run(run())


def test_partial_direct_provider_failure_prevents_automatic_selection():
    source = DirectDownloadSource()
    valid = DirectSearchResult(title='Book', author='Author', format='epub', language='en', size_bytes=123, download_url='https://fixture.invalid/book')
    good = Mock(name='good')
    good.search = AsyncMock(return_value=[valid])
    good.close = AsyncMock()
    bad = Mock(name='bad')
    bad.search = AsyncMock(side_effect=RuntimeError('private provider diagnostic'))
    bad.close = AsyncMock()
    source._providers = [good, bad]
    with pytest.raises(SearchError, match='Direct search failed'):
        source.search('Book', 'Author', strict=True)
    good.close.assert_awaited_once()
    bad.close.assert_awaited_once()
    # Manual search still offers the healthy source's results.
    assert len(source.search('Book', 'Author')) == 1


@pytest.mark.parametrize('status,html', [(403, 'blocked'), (429, 'limited'), (200, '<html>sign in</html>')])
def test_annas_failure_is_not_empty_and_does_not_retry_mirrors_or_solver(status, html):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(status, text=html)
    async def run():
        provider = AnnasArchiveProvider(mirror='https://fixture.invalid', flaresolverr_url='http://solver.invalid')
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with pytest.raises(SearchError, match='retry manually'):
                await provider.search('Book', strict=True)
        finally:
            await provider.close()
    asyncio.run(run())
    assert len(seen) == 1


def test_explicit_quota_failure_is_recorded_without_exposing_provider_body():
    async def run():
        provider = ZLibraryProvider(domain='fixture.invalid')
        provider._authenticated = True
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'success': 0, 'error': 'You have reached your daily download limit', 'session': 'private fixture session'})
        ))
        try:
            with pytest.raises(SearchError, match='quota is exhausted') as caught:
                await provider.search('Book', strict=True)
            assert 'private' not in str(caught.value)
        finally:
            await provider.close()
    asyncio.run(run())


@pytest.mark.parametrize('language,eligible', [
    ('English', True), ('en', True), ('eng', True), ('EN', True),
    ('English, German', False), ('en-unknown', False), ('enochian', False), ('', False),
])
def test_annas_language_evidence_survives_provider_to_orchestrator_pipeline(language, eligible):
    from types import SimpleNamespace
    from app.downloads.orchestrator import DownloadOrchestrator
    html = ('<table><tr><td></td><td><a href="/md5/fixture">The Gentleman</a></td>'
            '<td>Forrest Leo</td><td></td><td>2016</td><td></td><td></td>'
            f'<td>{language}</td><td>Book</td><td>epub</td><td>1 MB</td></tr></table>')
    async def run():
        provider = AnnasArchiveProvider(mirror='https://fixture.invalid')
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html)))
        try:
            results = await provider.search('The Gentleman', 'Forrest Leo', strict=True)
            assert len(results) == 1
            release = DirectDownloadSource()._convert_to_release(results[0], 'ebook')
            book = SimpleNamespace(title='The Gentleman', author='Forrest Leo')
            assert DownloadOrchestrator._direct_match(book, release, 'ebook') is eligible
        finally:
            await provider.close()
        # Manual parsing still offers unfamiliar labels for a person to review.
        assert len(provider._parse_search_results(html, 'ebook', provider.base_url)) == 1
    asyncio.run(run())
