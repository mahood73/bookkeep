"""Import regressions using real temporary files and a disposable SQLite database."""
from threading import Event
from unittest.mock import ANY, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AppSettings, Book, DownloadTask
from app.downloads.orchestrator import DownloadOrchestrator


@pytest.mark.parametrize("format_type,filename,configured,accepted", [
    ("ebook", "chapter.mp3", True, False),
    ("ebook", "chapter.mp3", False, False),
    ("audiobook", "book.epub", True, False),
    ("ebook", "nested/book.EPUB", True, True),
    ("audiobook", "nested/chapter.mp3", True, True),
    ("ebook", "cover.jpg", True, False),
])
def test_completed_download_requires_requested_format(tmp_path, format_type, filename, configured, accepted):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    source = tmp_path / "download"
    payload = source / filename
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"downloaded content")
    destination = tmp_path / "intake"
    destination.mkdir()
    with Session() as db:
        book = Book(title="Test Book", author="Test Author")
        db.add(book)
        db.flush()
        task = DownloadTask(book_id=book.id, format=format_type, source="manual", protocol="torrent")
        db.add(task)
        if configured:
            db.add(AppSettings(key=f"{format_type}_download_path", value=str(destination)))
        db.commit()
        task_id = task.id
        book_id = book.id
    handler = Mock()
    handler.download.return_value = str(source)
    with patch("app.downloads.orchestrator.SessionLocal", Session), patch(
        "app.downloads.orchestrator.get_handler", return_value=Mock(return_value=handler)
    ):
        DownloadOrchestrator()._execute_download(task_id, Event())
    with Session() as db:
        task = db.get(DownloadTask, task_id)
        book = db.get(Book, book_id)
        if accepted:
            assert task.state == "complete"
            assert task.import_status == "imported"
            assert (destination / "download" / filename).read_bytes() == b"downloaded content"
            assert getattr(book, f"{format_type}_available") is True
            handler.cleanup.assert_called_once_with(ANY, success=True)
        else:
            assert task.state == "error"
            assert task.import_status == "failed"
            assert "No supported" in task.import_message
            assert task.download_path == str(source)
            assert getattr(book, f"{format_type}_available") is False
            assert not list(destination.iterdir())
            handler.cleanup.assert_not_called()
        assert payload.read_bytes() == b"downloaded content"
    engine.dispose()
