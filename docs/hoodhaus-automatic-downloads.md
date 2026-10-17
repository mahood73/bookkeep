# Automatic source fallback

Issue: [mahood73/bookkeep#8](https://github.com/mahood73/bookkeep/issues/8)

New auto-approved requests, series requests, approval transitions and explicit
automatic retries share the orchestrator's Prowlarr-first policy. A successful
search with no suitable Prowlarr release can consult enabled direct providers.
Provider errors stop the attempt and leave a safe failure note for manual retry.

Direct selection requires an English release with matching returned title and
author after Unicode case, punctuation and whitespace normalisation, plus a
supported file format for the request. ISBN search text is not proof of identity.
Existing quality scores rank eligible editions only. Subtitles, alternate author
spellings and missing metadata can therefore require a manual selection.

Task creation serializes claims for a book in the database, so overlapping
manual/automatic selections cannot create a second active task for its format.
Automatic attempts also respect completed tasks and library availability.
Worker startup claims a queued task atomically across orchestrator instances.
An explicit manual selection can still redownload a completed item.

Automatic direct tasks attempt the first download source only, without cycling
to another source or retrying a blocked transfer through FlareSolverr. Manual
search and source fallback retain their existing behavior. Explicit provider
quota messages are classified safely; empty results and missing links do not
establish quota exhaustion.

This change adds no scheduler, backlog sweep or final library-import action.
Existing download staging and the operator's manual import review remain in
place. View-link behavior is tracked separately in #10.

## Verification

Tests use disposable SQLite databases, fixture providers and HTTP transports.
They exercise all four callers, identity/language/format filtering, source
failures, manual result preservation, concurrent task creation and worker
claims. No live provider, account, download or production database is used.
Live provider behavior and the historical reason for individual search misses
remain unverified.
