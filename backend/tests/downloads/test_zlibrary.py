"""Z-Library domain selection and API-to-download regression tests."""
import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import httpx
import pytest

from app.downloads.direct.providers.zlibrary import ZLibraryProvider
from app.downloads.handlers.direct import DirectHandler


def provider_with_transport(handler, domain=None):
    provider = ZLibraryProvider(email="reader@example.test", password="test-password", domain=domain)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return provider


@pytest.mark.parametrize("domain,expected", [(None, "z-lib.gd"), ("", "z-lib.gd"), ("  ", "z-lib.gd"), ("override.example", "override.example"), (" https://override.example/ ", "override.example")])
def test_domain_default_and_override(domain, expected):
    assert ZLibraryProvider(domain=domain).domain == expected


@pytest.mark.parametrize("domain", ["http://override.example", "https://user:secret@override.example", "override.example/path", "override.example?x=1", "override.example:444", "https://override.example/#x"])
def test_invalid_domain_is_rejected(domain):
    with pytest.raises(ValueError):
        ZLibraryProvider(domain=domain)


def login_response():
    return httpx.Response(200, json={"success": 1, "user": {"id": 42, "remix_userkey": "test-session-key", "personalDomains": ["ignored.example"]}})


def test_override_applies_to_login_search_and_resolution():
    seen = []
    def respond(request):
        seen.append(request)
        assert request.url.host == "override.example"
        if request.url.path == "/eapi/user/login":
            assert parse_qs(request.content.decode())["password"] == ["test-password"]
            return login_response()
        assert "remix_userkey=test-session-key" in request.headers.get("cookie", "")
        if request.url.path == "/eapi/book/search":
            fields = parse_qs(request.content.decode())
            assert fields["message"] == ["Pride and Prejudice Jane Austen"]
            assert "epub" in fields["extensions[]"]
            return httpx.Response(200, json={"success": 1, "books": [
                {"id": 123, "hash": "abc123", "title": "Pride and Prejudice", "author": "Jane Austen", "extension": "epub", "filesize": "1.5 MB", "language": "english", "year": "1813"},
                {"id": 124, "hash": "def456", "title": "Audio", "extension": "mp3"}]})
        assert request.url.path == "/eapi/book/123/abc123/file"
        return httpx.Response(200, json={"success": 1, "file": {"downloadLink": "/dl/book.epub?signed=test"}})
    async def run():
        p = provider_with_transport(respond, "override.example")
        try:
            assert await p.test_connection()
            results = await p.search("Pride and Prejudice", "Jane Austen")
            assert len(results) == 1
            result = results[0]
            assert result.download_url == "https://override.example/book/123/abc123"
            assert result.size_bytes == 1572864
            assert result.year == 1813
            assert result.language == "en"
            assert await p.resolve_download_url(result.download_url) == "https://override.example/dl/book.epub?signed=test"
        finally:
            await p.close()
    asyncio.run(run())
    assert sum(r.url.path == "/eapi/user/login" for r in seen) == 1


@pytest.mark.parametrize("status,payload", [(400, {"success": 0, "error": "Incorrect email or password"}), (200, {"success": 0}), (307, None), (513, None), (200, {"success": 1})])
def test_failed_login_does_not_try_another_domain(status, payload):
    seen = []
    def respond(request):
        seen.append(request)
        if payload is None:
            return httpx.Response(status, text="Verifying your browser | DiamWall", headers={"Location": "https://other.example/"})
        return httpx.Response(status, json=payload)
    async def run():
        p = provider_with_transport(respond, "override.example")
        try:
            assert not await p.test_connection()
        finally:
            await p.close()
    asyncio.run(run())
    assert len(seen) == 1
    assert seen[0].url.host == "override.example"


def test_isbn_search_uses_api_and_preserves_numeric_filesize():
    def respond(request):
        if request.url.path.endswith("/login"):
            return login_response()
        assert parse_qs(request.content.decode())["message"] == ["9780141439518"]
        return httpx.Response(200, json={"success": 1, "books": [{"id": 123, "hash": "abc123", "title": "Pride and Prejudice", "extension": "epub", "filesize": 1024}]})
    async def run():
        p = provider_with_transport(respond)
        try:
            results = await p.search("Ignored title", isbn="9780141439518")
            assert results[0].size_bytes == 1024
        finally:
            await p.close()
    asyncio.run(run())


def test_download_handler_resolves_api_and_streams_without_anna_page(tmp_path):
    settings = SimpleNamespace(zlibrary_domain="override.example", zlibrary_email="reader@example.test", zlibrary_password="test-password")
    db = Mock()
    db.query.return_value.first.return_value = settings
    task = SimpleNamespace(id=700, download_url="https://override.example/book/123/abc123", format="ebook", book=SimpleNamespace(title="Pride and Prejudice"), client_download_id=None)
    calls = []
    content = b"PK\x03\x04" + b"epub fixture" * 100
    def respond(request):
        calls.append(request)
        if request.url.path.endswith("/login"):
            return login_response()
        if request.url.path.endswith("/file"):
            assert "remix_userkey=test-session-key" in request.headers.get("cookie", "")
            return httpx.Response(200, json={"success": 1, "file": {"downloadLink": "https://files.example/book.epub"}})
        assert request.url.host == "files.example"
        assert "remix_userkey" not in request.headers.get("cookie", "")
        return httpx.Response(200, content=content, headers={"Content-Type": "application/epub+zip", "Content-Disposition": 'attachment; filename="book.epub"', "Content-Length": str(len(content))})
    handler = DirectHandler(db_session=db)
    p = provider_with_transport(respond, "override.example")
    with patch.object(handler, "_get_download_path", return_value=tmp_path), patch.object(handler, "_create_client", return_value=httpx.Client(transport=httpx.MockTransport(respond))), patch("app.downloads.handlers.direct.ZLibraryProvider", return_value=p), patch.object(handler, "_parse_annas_archive_sources", side_effect=AssertionError("Z-Library must not use Anna's Archive HTML")):
        result = handler.download(task, Event())
    assert result == str(tmp_path / "book.epub")
    assert (tmp_path / "book.epub").read_bytes() == content
    assert task.client_type == "direct"
    assert db.commit.call_count == 1
    assert len(calls) == 3
