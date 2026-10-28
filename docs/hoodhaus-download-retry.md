# Retrying failed downloads

The Downloads page retries a failed task through `POST /api/downloads/tasks/{id}/retry`.
The backend reconstructs the selected release from its stored metadata, including
size, indexer, protocol and direct-provider metadata. The browser sends only the
task ID. NZB, torrent and direct downloads share this path.

The original failure is removed only after a replacement task is committed and
its worker starts. If validation or worker startup fails, the original remains.
Refresh Downloads after an ambiguous network failure: a replacement may already
exist. Repeated or overlapping clicks cannot start a second active task for the
same book and format.

Retry refuses formats already marked available, active/completed downloads, and
tasks outside the failed state. Legacy tasks without a stored release JSON use
their existing URL/protocol and size zero when unknown; corrupt release data
requires selecting a release again. Retry does not fix an expired release URL.

A failed staging/import with retained downloaded files offers **Retry import**
instead. It copies those files again without starting a download; the task becomes
complete after staging succeeds. Completed/seeding tasks retain the existing
import action. A failed copy leaves the task and source files for inspection.

API errors show server messages and validation field names rather than
`[object Object]`. Submitted values and unknown error-object contents are not
included in toasts.

Restarting Bookkeep does not automatically retry failed tasks. Successful staging
means the file reached the configured destination (such as bookdrop), not that a
downstream library has ingested it.

Validation is offline with disposable databases, inert download workers and
synthetic files. Tests cover all three protocols and both book formats, retained
failures, overlapping retry requests, import-only recovery, and API error shapes.
No database migration is required. Deploy through a new fork image and a separate
HoodHaus image-pin MR. Roll back to the prior pinned image if necessary; tasks
already created remain ordinary download tasks.
