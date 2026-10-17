"""
Download orchestrator.

Manages the complete download workflow from search to completion.
"""
import os
import shutil
import threading
import unicodedata
from pathlib import Path
from typing import Optional, List, Dict
from threading import Event
from datetime import datetime, timezone
import structlog
from sqlalchemy.orm import Session
from sqlalchemy import text
from dataclasses import replace

from . import (
    Release,
    SearchError,
    DownloadState,
    DownloadStatus,
    get_source,
    get_handler,
    list_sources,
    list_handlers,
)
from ..models import Book, DownloadTask, AppSettings, DownloadClient, DirectDownloadSettings, BookRequest
from ..database import SessionLocal
from .prowlarr.utils import AUDIOBOOK_FORMATS, EBOOK_FORMATS

logger = structlog.get_logger()
ACTIVE_STATES = ('queued', 'downloading', 'checking', 'processing', 'paused')
FULFILLED_STATES = ('complete', 'seeding')


class DownloadOrchestrator:
    """
    Orchestrates book downloads from search to completion.

    Workflow:
    1. Search for releases via configured sources (Prowlarr, etc.)
    2. Select best release based on quality score
    3. Create download task
    4. Execute download via appropriate handler (torrent/usenet)
    5. Monitor progress
    6. Post-process downloaded files
    7. Update book availability
    """

    def __init__(self, db_session: Optional[Session] = None):
        """
        Initialize orchestrator.

        Args:
            db_session: Database session (will create if not provided)
        """
        self.db_session = db_session
        self._active_downloads: Dict[int, Event] = {}  # task_id -> cancel_event
        self._download_threads: Dict[int, threading.Thread] = {}

    def get_available_protocols(self, db: Optional[Session] = None, *, strict: bool = False) -> List[str]:
        """
        Get list of protocols that have enabled download clients configured.

        Args:
            db: Database session

        Returns:
            List of available protocols (e.g., ["torrent"], ["torrent", "usenet", "direct"])
        """
        session = db or self.db_session or SessionLocal()
        close_session = db is None and self.db_session is None

        try:
            # Query distinct protocols from enabled download clients
            enabled_clients = session.query(DownloadClient.protocol).filter(
                DownloadClient.enabled == True
            ).distinct().all()

            protocols = [client.protocol for client in enabled_clients if client.protocol]

            # Check if direct downloads are enabled
            direct_settings = session.query(DirectDownloadSettings).first()
            if direct_settings and direct_settings.enabled:
                protocols.append("direct")

            logger.debug(
                "orchestrator_available_protocols",
                protocols=protocols
            )

            return protocols

        except Exception as e:
            if strict:
                raise SearchError("Download client configuration could not be read; retry manually.") from None
            logger.error("orchestrator_get_protocols_failed", error=str(e))
            # Default to torrent if we can't determine (safer fallback)
            return ["torrent"]
        finally:
            if close_session:
                session.close()

    def search_releases(
        self,
        book: Book,
        format_type: str = "ebook",
        source_name: str = "prowlarr",
        *, strict: bool = False,
    ) -> List[Release]:
        """
        Search for book releases.

        Args:
            book: Book to search for
            format_type: "ebook" or "audiobook"
            source_name: Source to use (default: "prowlarr")

        Returns:
            List of Release objects sorted by quality
        """
        db = self.db_session or SessionLocal()
        try:
            source = get_source(source_name, db_session=db)

            logger.info(
                "orchestrator_search",
                book_id=book.id,
                title=book.title,
                author=book.author,
                format_type=format_type,
                source=source_name
            )

            releases = source.search(
                title=book.title,
                author=book.author,
                isbn=book.isbn,
                format_type=format_type,
                **({"strict": True} if strict else {}),
            )

            # Filter releases to only include protocols with configured clients
            available_protocols = self.get_available_protocols(db, strict=strict)
            total_before_filter = len(releases)

            if available_protocols or strict:
                releases = [r for r in releases if r.protocol in available_protocols]

            filtered_count = total_before_filter - len(releases)

            logger.info(
                "orchestrator_search_complete",
                book_id=book.id,
                releases_found=len(releases),
                releases_filtered=filtered_count,
                available_protocols=available_protocols,
                top_quality=releases[0].quality_score if releases else 0
            )

            return releases

        except Exception as e:
            if strict:
                if isinstance(e, SearchError):
                    raise
                label = 'Prowlarr' if source_name == 'prowlarr' else 'Direct'
                raise SearchError(f"{label} search failed; retry manually.") from None
            logger.error(
                "orchestrator_search_failed",
                book_id=book.id,
                error=str(e)
            )
            return []
        finally:
            if not self.db_session:
                db.close()

    def create_download_task(
        self,
        book: Book,
        release: Release,
        format_type: str,
        *, automatic: bool = False,
    ) -> Optional[DownloadTask]:
        """
        Create a download task from a release.

        Args:
            book: Book to download
            release: Selected release
            format_type: "ebook" or "audiobook"

        Returns:
            Created DownloadTask or None
        """
        db = self.db_session or SessionLocal()

        try:
            # Serialize claims for this book across sessions/workers. A no-op write
            # takes a row lock on PostgreSQL and a write lock on SQLite without
            # changing the book's updated_at timestamp.
            db.execute(text('UPDATE books SET id = id WHERE id = :id'), {'id': book.id})
            states = ACTIVE_STATES + (FULFILLED_STATES if automatic else ())
            existing = db.query(DownloadTask).filter(
                DownloadTask.book_id == book.id, DownloadTask.format == format_type,
                DownloadTask.state.in_(states),
            ).first()
            if existing:
                db.commit()
                return existing
            if automatic:
                available = db.query(getattr(Book, f'{format_type}_available')).filter(Book.id == book.id).scalar()
                if available:
                    db.commit()
                    return None
            # Store release data as JSON
            import json
            from datetime import datetime

            # Custom JSON encoder to handle datetime objects
            def json_serializer(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            release_data = {
                "source": release.source,
                "title": release.title,
                "download_url": release.download_url,
                "protocol": release.protocol,
                "size_bytes": release.size_bytes,
                "seeders": release.seeders,
                "leechers": release.leechers,
                "indexer": release.indexer,
                "indexer_id": release.indexer_id,
                "category": release.category,
                "format": release.format,
                "language": release.language,
                "quality_score": release.quality_score,
                "publish_date": release.publish_date.isoformat() if release.publish_date else None,
                "metadata": release.metadata,
            }

            # Compute hash from download URL for tracking
            import hashlib
            info_hash = hashlib.sha256(release.download_url.encode()).hexdigest()[:16]

            task = DownloadTask(
                book_id=book.id,
                format=format_type,
                source=release.source,
                release_title=release.title,
                download_url=release.download_url,
                protocol=release.protocol,
                state="queued",
                progress=0.0,
                release_data_json=json.dumps(release_data, default=json_serializer),
                info_hash=info_hash,
            )

            db.add(task)
            db.commit()
            db.refresh(task)

            logger.info(
                "orchestrator_task_created",
                task_id=task.id,
                book_id=book.id,
                format=format_type,
                protocol=release.protocol,
                quality=release.quality_score
            )

            return task

        except Exception as e:
            logger.error(
                "orchestrator_create_task_failed",
                book_id=book.id,
                error=str(e)
            )
            db.rollback()
            return None

        finally:
            if not self.db_session:
                db.close()

    def start_download(self, task_id: int) -> bool:
        """
        Start a download task in a background thread.

        Args:
            task_id: Download task ID

        Returns:
            True if download started successfully
        """
        db = self.db_session or SessionLocal()
        task = None

        try:
            task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if not task:
                logger.error("orchestrator_task_not_found", task_id=task_id)
                return False

            # Only one worker may claim a queued task, even when different
            # orchestrator instances are serving overlapping HTTP requests.
            claimed = db.query(DownloadTask).filter(
                DownloadTask.id == task_id, DownloadTask.state == 'queued',
            ).update({DownloadTask.state: 'processing'}, synchronize_session=False)
            db.commit()
            db.refresh(task)
            if not claimed:
                return task.state in ACTIVE_STATES + FULFILLED_STATES

            # Create cancel event
            cancel_event = Event()
            self._active_downloads[task_id] = cancel_event

            # Start download thread
            thread = threading.Thread(
                target=self._execute_download,
                args=(task_id, cancel_event),
                daemon=True
            )
            self._download_threads[task_id] = thread
            thread.start()

            logger.info("orchestrator_download_started", task_id=task_id)
            return True

        except Exception as e:
            db.rollback()
            if task:
                task.state = 'error'
                task.message = 'Download could not start; retry manually.'
                db.commit()
            self._active_downloads.pop(task_id, None)
            self._download_threads.pop(task_id, None)
            logger.error("orchestrator_start_failed", task_id=task_id)
            return False

        finally:
            if not self.db_session:
                db.close()

    def _execute_download(self, task_id: int, cancel_event: Event):
        """
        Execute download in background thread.

        Args:
            task_id: Download task ID
            cancel_event: Event to signal cancellation
        """
        db = SessionLocal()

        try:
            task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if not task:
                logger.error("orchestrator_execute_task_not_found", task_id=task_id)
                return

            # Update state to downloading
            task.state = "downloading"
            db.commit()

            # Get appropriate handler based on protocol
            if task.protocol == "torrent":
                handler_name = "torrent"
            elif task.protocol == "usenet":
                handler_name = "usenet"
            elif task.protocol == "direct":
                handler_name = "direct"
            else:
                logger.error("orchestrator_unknown_protocol", task_id=task_id, protocol=task.protocol)
                task.state = "error"
                task.message = f"Unknown protocol: {task.protocol}"
                db.commit()
                return

            HandlerClass = get_handler(handler_name)
            handler = HandlerClass(db_session=db)

            # Progress callback
            def progress_callback(progress: float):
                task.progress = progress
                db.commit()

            # Status callback
            def status_callback(status: DownloadStatus):
                # A handler can report QUEUED while resolving its selected source.
                # The task already has a worker; don't make it claimable again.
                task.state = 'processing' if status.state == DownloadState.QUEUED else status.state.value
                task.progress = status.progress
                if status.message:
                    task.message = status.message
                if status.client_state:
                    task.client_state = status.client_state
                db.commit()

                logger.info(
                    "orchestrator_download_progress",
                    task_id=task_id,
                    state=status.state.value,
                    progress=status.progress,
                    message=status.message,
                    client_state=status.client_state
                )

            # Execute download
            download_path = handler.download(
                task=task,
                cancel_flag=cancel_event,
                progress_callback=progress_callback,
                status_callback=status_callback,
            )

            if download_path:
                # Success - copy/hardlink to destination
                dest_path = self._copy_to_destination(task, download_path, db)

                if dest_path is None:
                    task.state = "error"
                    task.message = task.import_message
                    task.download_path = download_path
                    db.commit()
                    # Download succeeded: retain the torrent/files for inspection.
                    # Failure cleanup would delete the original downloaded data.
                    return

                # Import succeeded, including downloads intentionally kept in place.
                final_path = dest_path

                task.state = "complete"
                task.progress = 100.0
                task.download_path = final_path
                db.commit()

                # Cleanup
                handler.cleanup(task, success=True)

                # Only update book availability if import succeeded (dest_path is not None)
                # This ensures books are only marked as available after successful import
                if dest_path:
                    self._update_book_availability(task, db)

                logger.info(
                    "orchestrator_download_complete",
                    task_id=task_id,
                    source_path=download_path,
                    final_path=final_path
                )

            else:
                # Failed
                if task.state != "paused":  # Don't override paused state
                    task.state = "error"
                    task.message = task.message or 'Download failed; check the download log and retry manually.'
                db.commit()

                # Cleanup
                handler.cleanup(task, success=False)

                logger.error("orchestrator_download_failed", task_id=task_id)

        except Exception as e:
            logger.error("orchestrator_execute_error", task_id=task_id, error=str(e))

            # Update task state
            try:
                task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
                if task:
                    task.state = "error"
                    task.message = 'Download failed; check the download log and retry manually.'
                    db.commit()
            except:
                pass

        finally:
            # Clean up
            if task_id in self._active_downloads:
                del self._active_downloads[task_id]
            if task_id in self._download_threads:
                del self._download_threads[task_id]

            db.close()

    def _copy_to_destination(self, task: DownloadTask, source_path: str, db: Session) -> Optional[str]:
        """
        Copy or hardlink downloaded files to the configured destination path.

        Args:
            task: Download task
            source_path: Path where the file was downloaded by the client
            db: Database session

        Returns:
            Destination path if successful, None otherwise
        """
        from datetime import datetime, timezone

        # Mark import as starting
        task.import_status = 'importing'
        task.import_message = 'Starting import...'
        db.commit()

        try:
            # Check actual files before copying or declaring availability, including
            # downloads kept in place when no destination is configured.
            source = Path(source_path)
            if not source.exists():
                task.import_status = 'failed'
                task.import_message = f'Source file not found: {source_path}'
                db.commit()
                return None

            supported_formats = {
                "ebook": EBOOK_FORMATS,
                "audiobook": AUDIOBOOK_FORMATS,
            }.get(task.format, set())
            files = (source,) if source.is_file() else source.rglob("*")
            if not any(
                file.is_file() and file.suffix.lower().lstrip(".") in supported_formats
                for file in files
            ):
                task.import_status = 'failed'
                task.import_message = f'No supported {task.format} files found in download; source retained.'
                db.commit()
                return None

            # Get configured destination path based on format
            setting_key = f"{task.format}_download_path"  # e.g., "ebook_download_path"
            setting = db.query(AppSettings).filter(AppSettings.key == setting_key).first()

            if not setting or not setting.value:
                logger.warning(
                    "orchestrator_no_destination_configured",
                    task_id=task.id,
                    format=task.format,
                    message=f"No destination path configured for {task.format}. Files will remain in download client location."
                )
                return source_path

            dest_base = setting.value
            if not os.path.exists(dest_base):
                logger.error(
                    "orchestrator_destination_not_found",
                    task_id=task.id,
                    dest_base=dest_base
                )
                # Mark import as failed
                task.import_status = 'failed'
                task.import_message = f'Destination path does not exist: {dest_base}'
                db.commit()
                return None

            # Determine destination name
            if source.is_file():
                dest_name = source.name
                dest_path = Path(dest_base) / dest_name
            else:
                # It's a directory
                dest_name = source.name
                dest_path = Path(dest_base) / dest_name

            # Check if destination already exists
            if dest_path.exists():
                logger.info(
                    "orchestrator_destination_exists",
                    task_id=task.id,
                    dest_path=str(dest_path),
                    message="Destination already exists, skipping copy"
                )
                # Mark as imported (already exists)
                task.import_status = 'imported'
                task.import_message = f'File already exists at destination: {dest_path.name}'
                task.imported_at = datetime.now(timezone.utc)
                db.commit()
                return str(dest_path)

            # Check if hardlinks are enabled — prefer format-specific setting,
            # fall back to the global "use_hardlinks" (default: true)
            format_key = f"use_hardlinks_{task.format}"  # e.g. "use_hardlinks_ebook"
            format_setting = db.query(AppSettings).filter(
                AppSettings.key == format_key
            ).first()
            if format_setting is not None:
                use_hardlinks = format_setting.value != "false"
            else:
                global_setting = db.query(AppSettings).filter(
                    AppSettings.key == "use_hardlinks"
                ).first()
                use_hardlinks = not (global_setting and global_setting.value == "false")

            if use_hardlinks:
                # Try to hardlink first (fast, no extra space), fall back to copy
                try:
                    if source.is_file():
                        os.link(str(source), str(dest_path))
                        logger.info(
                            "orchestrator_hardlink_success",
                            task_id=task.id,
                            source=str(source),
                            dest=str(dest_path)
                        )
                    else:
                        shutil.copytree(str(source), str(dest_path), copy_function=os.link)
                        logger.info(
                            "orchestrator_hardlink_dir_success",
                            task_id=task.id,
                            source=str(source),
                            dest=str(dest_path)
                        )
                except (OSError, PermissionError) as e:
                    # Hardlink failed (maybe cross-device), fall back to copy
                    logger.info(
                        "orchestrator_hardlink_failed_copying",
                        task_id=task.id,
                        error=str(e),
                        message="Hardlink failed, falling back to copy"
                    )

                    if source.is_file():
                        shutil.copy2(str(source), str(dest_path))
                        logger.info(
                            "orchestrator_copy_success",
                            task_id=task.id,
                            source=str(source),
                            dest=str(dest_path)
                        )
                    else:
                        shutil.copytree(str(source), str(dest_path))
                        logger.info(
                            "orchestrator_copy_dir_success",
                            task_id=task.id,
                            source=str(source),
                            dest=str(dest_path)
                        )
            else:
                # Hardlinks disabled, copy directly
                if source.is_file():
                    shutil.copy2(str(source), str(dest_path))
                    logger.info(
                        "orchestrator_copy_success",
                        task_id=task.id,
                        source=str(source),
                        dest=str(dest_path)
                    )
                else:
                    shutil.copytree(str(source), str(dest_path))
                    logger.info(
                        "orchestrator_copy_dir_success",
                        task_id=task.id,
                        source=str(source),
                        dest=str(dest_path)
                    )

            # Mark import as successful
            task.import_status = 'imported'
            task.import_message = f'Successfully imported to: {dest_path.name}'
            task.imported_at = datetime.now(timezone.utc)
            db.commit()

            return str(dest_path)

        except Exception as e:
            logger.error(
                "orchestrator_copy_error",
                task_id=task.id,
                error=str(e)
            )
            # Mark import as failed
            task.import_status = 'failed'
            task.import_message = f'Import failed: {str(e)}'
            db.commit()
            return None

    def _update_book_availability(self, task: DownloadTask, db: Session):
        """
        Update book availability after successful download.

        Args:
            task: Completed download task
            db: Database session
        """
        try:
            book = db.query(Book).filter(Book.id == task.book_id).first()
            if not book:
                return

            # Update availability flags
            if task.format == "ebook":
                book.ebook_available = True
            elif task.format == "audiobook":
                book.audiobook_available = True

            # Store the download hashes for duplicate detection
            import json
            import hashlib

            try:
                hashes = json.loads(book.downloaded_release_hashes) if book.downloaded_release_hashes else []
            except (json.JSONDecodeError, TypeError):
                hashes = []

            hashes_to_add = []

            # Add torrent/NZB info hash if available
            if task.info_hash:
                hashes_to_add.append(task.info_hash)

            # Also add URL-based hash for Prowlarr duplicate detection
            if task.download_url:
                url_hash = hashlib.sha256(task.download_url.encode()).hexdigest()[:16]
                hashes_to_add.append(url_hash)

            # Add new hashes
            for hash_val in hashes_to_add:
                if hash_val not in hashes:
                    hashes.append(hash_val)

            book.downloaded_release_hashes = json.dumps(hashes)

            db.commit()

            logger.info(
                "orchestrator_book_updated",
                book_id=book.id,
                format=task.format,
                available=True,
                hash_stored=task.info_hash is not None
            )

        except Exception as e:
            logger.error(
                "orchestrator_update_book_failed",
                task_id=task.id,
                error=str(e)
            )

    def cancel_download(self, task_id: int) -> bool:
        """
        Cancel an active download.

        Args:
            task_id: Download task ID

        Returns:
            True if cancelled successfully
        """
        if task_id not in self._active_downloads:
            logger.warning("orchestrator_cancel_not_active", task_id=task_id)
            return False

        try:
            # Signal cancellation
            cancel_event = self._active_downloads[task_id]
            cancel_event.set()

            logger.info("orchestrator_download_cancelled", task_id=task_id)
            return True

        except Exception as e:
            logger.error("orchestrator_cancel_failed", task_id=task_id, error=str(e))
            return False

    def pause_download(self, task_id: int) -> bool:
        """
        Pause a download.

        Args:
            task_id: Download task ID

        Returns:
            True if paused successfully
        """
        db = self.db_session or SessionLocal()

        try:
            task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if not task:
                return False

            # Get handler
            handler_name = "torrent" if task.protocol == "torrent" else "usenet"
            HandlerClass = get_handler(handler_name)
            handler = HandlerClass(db_session=db)

            # Pause in client
            success = handler.pause(task)

            if success:
                task.state = "paused"
                db.commit()

                # Also cancel the monitoring thread
                if task_id in self._active_downloads:
                    self._active_downloads[task_id].set()

            return success

        except Exception as e:
            logger.error("orchestrator_pause_failed", task_id=task_id, error=str(e))
            return False

        finally:
            if not self.db_session:
                db.close()

    def resume_download(self, task_id: int) -> bool:
        """
        Resume a paused download.

        Args:
            task_id: Download task ID

        Returns:
            True if resumed successfully
        """
        db = self.db_session or SessionLocal()

        try:
            task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if not task:
                return False

            # Get handler
            handler_name = "torrent" if task.protocol == "torrent" else "usenet"
            HandlerClass = get_handler(handler_name)
            handler = HandlerClass(db_session=db)

            # Resume in client
            success = handler.resume(task)

            if success:
                # Restart monitoring
                task.state = 'queued'
                db.commit()
                return self.start_download(task_id)

            return False

        except Exception as e:
            logger.error("orchestrator_resume_failed", task_id=task_id, error=str(e))
            return False

        finally:
            if not self.db_session:
                db.close()

    @staticmethod
    def _direct_match(book: Book, release: Release, format_type: str) -> bool:
        def normalize(value):
            if not isinstance(value, str):
                return ''
            return ' '.join(''.join(c for c in unicodedata.normalize('NFKC', value).casefold()
                                   if c.isalnum() or c.isspace()).split())

        formats = AUDIOBOOK_FORMATS if format_type == 'audiobook' else EBOOK_FORMATS
        title, author = normalize(book.title), normalize(book.author)
        metadata = release.metadata if isinstance(release.metadata, dict) else {}
        language = release.language.strip().lower() if isinstance(release.language, str) else ''
        file_format = release.format.lower().lstrip('.') if isinstance(release.format, str) else ''
        return bool(
            title and author
            and normalize(release.title) == title
            and normalize(metadata.get('author')) == author
            and language in {'en', 'eng', 'english'}
            and file_format in formats
            and release.protocol == 'direct'
        )

    def search_and_download(
        self,
        book: Book,
        format_type: str = 'ebook',
        source_name: Optional[str] = None,
    ) -> Optional[DownloadTask]:
        """Fulfil a new request or explicit retry, using Prowlarr before direct sources."""
        db = self.db_session or SessionLocal()
        try:
            return self._automatic_download(db, book, format_type, source_name)
        except SearchError as exc:
            message = f'[Automatic download] {exc}'
            for request in db.query(BookRequest).filter(
                BookRequest.book_id == book.id, BookRequest.format == format_type,
                BookRequest.status.in_(['approved', 'processing']),
            ).all():
                if message not in (request.admin_notes or ''):
                    request.admin_notes = ((request.admin_notes or '') + '\n' + message).strip()
            db.commit()
            logger.warning('automatic_download_failed', book_id=book.id, format=format_type, message=str(exc))
            raise
        finally:
            if not self.db_session:
                db.close()

    def _automatic_download(self, db, book, format_type, source_name):
        if format_type not in {'ebook', 'audiobook'}:
            raise SearchError('Unsupported request format; select ebook or audiobook.')
        existing = db.query(DownloadTask).filter(
            DownloadTask.book_id == book.id, DownloadTask.format == format_type,
            DownloadTask.state.in_(ACTIVE_STATES + FULFILLED_STATES),
        ).first()
        if existing:
            return existing
        if db.query(getattr(Book, f'{format_type}_available')).filter(Book.id == book.id).scalar():
            return None
        for name in ([source_name] if source_name else ['prowlarr', 'direct']):
            if name == 'direct' and 'direct' not in self.get_available_protocols(db, strict=True):
                continue
            releases = self.search_releases(book, format_type, name, strict=True)
            if name == 'direct':
                releases = [r for r in releases if self._direct_match(book, r, format_type)]
            if not releases:
                continue
            best_release = max(releases, key=lambda release: release.quality_score)
            best_release = replace(best_release, metadata={**best_release.metadata, 'automatic_selection': True})
            task = self.create_download_task(book, best_release, format_type, automatic=True)
            if task and self.start_download(task.id):
                return task
            # A selected download failure is not permission to try another source.
            if task and task.state == 'queued':
                task.state = 'error'
                task.message = 'Selected download could not start; retry manually.'
                db.commit()
            raise SearchError('Selected download could not start; check Downloads and retry manually.')
        return None

    def get_active_downloads(self) -> List[int]:
        """
        Get list of active download task IDs.

        Returns:
            List of task IDs
        """
        return list(self._active_downloads.keys())

    def is_downloading(self, task_id: int) -> bool:
        """
        Check if a task is currently downloading.

        Args:
            task_id: Download task ID

        Returns:
            True if actively downloading
        """
        return task_id in self._active_downloads

    def get_download_count(self) -> int:
        """
        Get number of active downloads.

        Returns:
            Active download count
        """
        return len(self._active_downloads)
