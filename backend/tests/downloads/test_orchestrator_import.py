Not privileged to set domain environment.
"""Import regressions using real temporary files and a disposable SQLite database."""
from threading import Event
import errno
import os
import stat
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


@pytest.mark.parametrize("format_type,extension", [("ebook", "epub"), ("audiobook", "m4b")])
@pytest.mark.parametrize("hardlinks", [False, True])
@pytest.mark.parametrize("link_failure", [None, errno.EXDEV, errno.EPERM])
def test_staged_directories_allow_cleanup_without_changing_sources(
    tmp_path, format_type, extension, hardlinks, link_failure
):
    """A consumer with the staging owner's identity can remove every staged file."""
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    source = tmp_path / "download"
    nested = source / "nested"
    nested.mkdir(parents=True)
    files = [source / f"one.{extension}", nested / f"two.{extension}"]
    for file in files:
        file.write_bytes(b"original download")
        file.chmod(0o444)
    nested.chmod(0o555)
    source.chmod(0o555)
    originals = {p: (p.stat().st_uid, p.stat().st_gid, p.stat().st_mode, p.read_bytes()) for p in files}
    destination = tmp_path / "intake"
    destination.mkdir()
    with Session() as db:
        book = Book(title="Staging fixture", author="Fixture")
        db.add(book)
        db.flush()
        task = DownloadTask(book_id=book.id, format=format_type, source="manual", protocol="torrent")
        db.add(task)
        db.add_all([
            AppSettings(key=f"{format_type}_download_path", value=str(destination)),
            AppSettings(key=f"use_hardlinks_{format_type}", value="true" if hardlinks else "false"),
        ])
        db.commit()
        task_id = task.id
    handler = Mock()
    handler.download.return_value = str(source)
    real_link = os.link
    link_attempts = []
    copied_sources = set()
    def try_link(src, dst):
        # Leave one successful link before a later failure to exercise a mixed tree.
        link_attempts.append(src)
        if link_failure is not None and len(link_attempts) == 2:
            copied_sources.add(str(src))
            raise OSError(link_failure, "fixture hardlink unavailable")
        return real_link(src, dst)
    try:
        with patch("app.downloads.orchestrator.SessionLocal", Session), patch(
            "app.downloads.orchestrator.get_handler", return_value=Mock(return_value=handler)
        ), patch("os.link", side_effect=try_link):
            DownloadOrchestrator()._execute_download(task_id, Event())
        with Session() as db:
            task = db.get(DownloadTask, task_id)
            assert task.state == "complete", task.import_message
            assert task.import_status == "imported"
        staged_root = destination / source.name
        for directory in (staged_root, staged_root / "nested"):
            assert stat.S_IMODE(directory.stat().st_mode) & 0o700 == 0o700
            assert directory.stat().st_uid == os.getuid()
        for original in files:
            staged = staged_root / original.relative_to(source)
            assert staged.read_bytes() == b"original download"
            linked = hardlinks and str(original) not in copied_sources
            assert (staged.stat().st_ino == original.stat().st_ino) is linked
            staged.unlink()
            assert not staged.exists()
            assert originals[original] == (original.stat().st_uid, original.stat().st_gid, original.stat().st_mode, original.read_bytes())
        assert stat.S_IMODE(source.stat().st_mode) == 0o555
        assert stat.S_IMODE(nested.stat().st_mode) == 0o555
        (staged_root / "nested").rmdir()
        staged_root.rmdir()
        handler.cleanup.assert_called_once_with(ANY, success=True)
    finally:
        # Source fixtures intentionally remain read-only throughout staging.
        source.chmod(0o755)
        nested.chmod(0o755)
        engine.dispose()
