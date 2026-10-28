"""Retry via the real HTTP router, stored releases, and disposable databases."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.auth import get_current_user
from app.database import Base, get_db
from app.downloads.orchestrator import DownloadOrchestrator
from app.routers import downloads


@pytest.fixture
def retry_library(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    (tmp_path / "ebooks").mkdir()
    (tmp_path / "audio").mkdir()
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    worker = Mock()
    monkeypatch.setattr("app.downloads.orchestrator.threading", SimpleNamespace(Thread=worker))
    monkeypatch.setattr("app.downloads.orchestrator.SessionLocal", sessions)
    with sessions() as db:
        book = models.Book(title="Fixture book", author="Fixture author")
        db.add_all([book, models.AppSettings(key="ebook_download_path", value=str(tmp_path / "ebooks")),
                    models.AppSettings(key="audiobook_download_path", value=str(tmp_path / "audio"))])
        db.commit()
        app = FastAPI()
        app.include_router(downloads.router, prefix="/api/downloads")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
        def request_session():
            with sessions() as request_db:
                yield request_db
        app.dependency_overrides[get_db] = request_session
        with TestClient(app) as client:
            yield SimpleNamespace(db=db, book=book, client=client, worker=worker, tmp_path=tmp_path)
    engine.dispose()


def failed_task(library, protocol="usenet", fmt="ebook", **overrides):
    release = dict(source="prowlarr" if protocol != "direct" else "direct", title="Exact original release",
                   download_url="https://fixture.invalid/release", protocol=protocol, size_bytes=2048,
                   indexer="Fixture indexer", indexer_id=7, seeders=3, language="en", format="epub",
                   metadata={"automatic_selection": True, "provider": "fixture"})
    fields = dict(book_id=library.book.id, format=fmt, source=release["source"], state="error",
                  release_title=release["title"], download_url=release["download_url"], protocol=protocol,
                  message="Original failure", release_data_json=json.dumps(release))
    fields.update(overrides)
    task = models.DownloadTask(**fields)
    library.db.add(task)
    library.db.commit()
    return task


@pytest.mark.parametrize("protocol", ["usenet", "torrent", "direct"])
@pytest.mark.parametrize("fmt", ["ebook", "audiobook"])
def test_retry_uses_stored_release_without_browser_metadata(retry_library, protocol, fmt):
    lib = retry_library
    old = failed_task(lib, protocol, fmt)
    old_id, old_source = old.id, old.source
    response = lib.client.post(f"/api/downloads/tasks/{old_id}/retry")
    assert response.status_code == 200, response.text
    lib.db.expire_all()
    task = lib.db.get(models.DownloadTask, response.json()["task_id"])
    assert task.id != old_id
    assert lib.db.get(models.DownloadTask, old_id) is None
    assert (task.protocol, task.format, task.source) == (protocol, fmt, old_source)
    release = json.loads(task.release_data_json)
    assert release["size_bytes"] == 2048
    assert release["indexer"] == "Fixture indexer"
    assert release["indexer_id"] == 7
    assert release["metadata"] == {"automatic_selection": True, "provider": "fixture"}
    assert task.state == "processing"
    assert lib.worker.return_value.start.call_count == 1
    # A second click with the stale original ID cannot start another worker.
    assert lib.client.post(f"/api/downloads/tasks/{old_id}/retry").status_code == 404
    assert lib.worker.return_value.start.call_count == 1


def test_worker_start_failure_retains_original_and_failed_replacement(retry_library):
    lib = retry_library
    old = failed_task(lib)
    lib.worker.return_value.start.side_effect = RuntimeError("fixture start failure")
    response = lib.client.post(f"/api/downloads/tasks/{old.id}/retry")
    assert response.status_code == 502
    lib.db.expire_all()
    assert lib.db.get(models.DownloadTask, old.id).message == "Original failure"
    assert all(t.state == "error" for t in lib.db.query(models.DownloadTask).all())


@pytest.mark.parametrize("changes", [
    {"download_url": None}, {"protocol": None}, {"protocol": "unknown"}, {"format": "physical"},
    {"release_data_json": "invalid-json"}, {"release_data_json": "[]"},
    {"release_data_json": '{"size_bytes": "not-a-number"}'},
    {"release_data_json": '{"size_bytes": -1}'},
    {"release_data_json": '{"metadata": []}'},
    {"release_data_json": '{"publish_date": "invalid-date"}'},
])
def test_invalid_stored_task_is_retained(retry_library, changes):
    lib = retry_library
    old = failed_task(lib, **changes)
    response = lib.client.post(f"/api/downloads/tasks/{old.id}/retry")
    assert response.status_code == 400, response.text
    assert lib.db.get(models.DownloadTask, old.id).state == "error"
    assert lib.db.query(models.DownloadTask).count() == 1
    lib.worker.assert_not_called()


@pytest.mark.parametrize("state", ["queued", "processing", "downloading", "paused", "complete", "seeding"])
def test_retry_rejects_non_failed_task(retry_library, state):
    lib = retry_library
    old = failed_task(lib, state=state)
    assert lib.client.post(f"/api/downloads/tasks/{old.id}/retry").status_code == 409
    assert lib.db.get(models.DownloadTask, old.id).state == state
    lib.worker.assert_not_called()


@pytest.mark.parametrize("block", ["available", "active", "fulfilled", "missing_path"])
def test_retry_does_not_redownload_owned_or_active_books(retry_library, block):
    lib = retry_library
    old = failed_task(lib)
    if block == "available":
        lib.book.ebook_available = True
    elif block in ("active", "fulfilled"):
        failed_task(lib, state="processing" if block == "active" else "complete")
    else:
        lib.db.query(models.AppSettings).delete()
    lib.db.commit()
    response = lib.client.post(f"/api/downloads/tasks/{old.id}/retry")
    assert response.status_code == (400 if block == "missing_path" else 409)
    assert lib.db.get(models.DownloadTask, old.id).message == "Original failure"
    lib.worker.assert_not_called()


def test_legacy_task_without_release_json_can_retry_with_unknown_size(retry_library):
    lib = retry_library
    old = failed_task(lib, release_data_json=None)
    response = lib.client.post(f"/api/downloads/tasks/{old.id}/retry")
    assert response.status_code == 200
    task = lib.db.get(models.DownloadTask, response.json()["task_id"])
    assert json.loads(task.release_data_json)["size_bytes"] == 0


def test_import_failure_retries_copy_instead_of_download(retry_library):
    lib = retry_library
    source = lib.tmp_path / "download.epub"
    source.write_bytes(b"fixture epub")
    old = failed_task(lib, import_status="failed", download_path=str(source))
    response = lib.client.post(f"/api/downloads/tasks/{old.id}/retry")
    assert response.status_code == 409
    assert "import" in response.json()["detail"].lower()
    response = lib.client.post(f"/api/downloads/import/{old.id}")
    assert response.status_code == 200, response.text
    lib.db.expire_all()
    assert lib.db.get(models.DownloadTask, old.id).state == "complete"
    assert lib.db.get(models.DownloadTask, old.id).import_status == "imported"
    assert lib.db.get(models.Book, lib.book.id).ebook_available
    assert source.read_bytes() == b"fixture epub"
    lib.worker.assert_not_called()


def test_manual_download_requires_release_size_but_never_deletes_existing_task(retry_library):
    lib = retry_library
    old = failed_task(lib)
    body = dict(book_id=old.book_id, format_type=old.format, download_url=old.download_url,
                protocol=old.protocol, release_title=old.release_title, indexer="fixture")
    response = lib.client.post("/api/downloads/download", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "size_bytes"]
    assert lib.db.get(models.DownloadTask, old.id).state == "error"


@pytest.mark.parametrize("initial_status", ["approved", "not_found"])
def test_successful_retry_returns_existing_request_to_processing(retry_library, initial_status):
    lib = retry_library
    user = models.User(username="fixture", email="fixture@example.invalid")
    lib.db.add(user)
    lib.db.flush()
    request = models.BookRequest(book_id=lib.book.id, user_id=user.id, format="ebook", status=initial_status)
    lib.db.add(request)
    old = failed_task(lib)
    assert lib.client.post(f"/api/downloads/tasks/{old.id}/retry").status_code == 200
    lib.db.expire_all()
    assert lib.db.get(models.BookRequest, request.id).status == "processing"


def test_overlapping_retry_clicks_start_only_one_replacement(retry_library):
    from concurrent.futures import ThreadPoolExecutor
    lib = retry_library
    old_id = failed_task(lib).id
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: lib.client.post(f"/api/downloads/tasks/{old_id}/retry"), range(2)))
    assert sorted(r.status_code for r in responses)[0] == 200
    assert sum(r.status_code == 200 for r in responses) == 1
    assert all(r.status_code in (200, 404, 409) for r in responses)
    lib.db.expire_all()
    assert lib.db.query(models.DownloadTask).count() == 1
    assert lib.worker.return_value.start.call_count == 1


def test_failed_import_keeps_the_task_and_original_files(retry_library):
    lib = retry_library
    source = lib.tmp_path / "retained.epub"
    source.write_bytes(b"retained fixture")
    old = failed_task(lib, import_status="failed", download_path=str(source))
    lib.db.query(models.AppSettings).filter(models.AppSettings.key == "ebook_download_path").one().value = str(lib.tmp_path / "missing-destination")
    lib.db.commit()
    response = lib.client.post(f"/api/downloads/import/{old.id}")
    assert response.status_code == 500
    lib.db.expire_all()
    task = lib.db.get(models.DownloadTask, old.id)
    assert task.state == "error" and task.import_status == "failed"
    assert task.download_path == str(source)
    assert source.read_bytes() == b"retained fixture"
    lib.worker.assert_not_called()
