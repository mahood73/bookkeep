# Automatic fulfilment for Hardcover list requests

Reported example: Station Eleven, requested through Hardcover Want-to-read
sync after v1.6.2-hoodhaus.8 was deployed. The .8 fallback covered direct UI
requests, series requests, approval and explicit retry, but the list-sync caller
only persisted an approved request and never invoked automatic fulfilment.

A disposable SQLite regression follows actual list sync through the download
orchestrator and reads the Requests and Downloads interfaces. Before the fix,
the request stayed approved and no download task existed. External Hardcover,
Prowlarr and direct-provider responses are fixtures. The download worker is
inert, while task creation and claiming remain real.

The selected repair calls the existing orchestrator only after a new
Hardcover-origin request has been committed and auto-approved. It keeps the
existing Prowlarr-first, English-only, normalized title-and-author direct
matching rules. A returned task moves the request to processing. Search and
selected-download failures retain the existing manual-retry notes and do not
abort later new requests in the sync.

Pending requests still require approval. Existing requests, including the
already affected Station Eleven request, are not replayed or swept. They need
an explicit retry. Repeat list sync must neither create duplicate tasks nor
retry a failed attempt. No provider settings, credentials, schedules or manual
library-import boundaries change.

Tests cover Want-to-read, custom lists and overlapping membership; ebook,
audiobook and both formats; duplicate sync; approval, permission and availability
gates; existing approved/not-found/processing requests; uncertain and empty
results; Prowlarr, direct-source and worker failures; and continuation after one
format fails. No production request or live provider was used for validation.

This is the third independent repair alongside fork PRs #13 and #14. The
planned production rollout is one deployment after all three are merged and
the final source/image has been validated. Merge, image publication and
production deployment are separate approval steps.
