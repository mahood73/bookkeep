# Reviewed Hardcover matches

Admins can choose **Correct Hardcover match** on a stored book's details page. Enter a numeric Hardcover book ID, review the canonical work's title, author and collection label, then confirm. Collection labels can be incomplete. Settings → General → Hardcover matches to review lists unresolved library candidates, including local books without a Hardcover match.

Preview does not change catalogue data. Confirmation requires an unexpired signed preview bound to the same admin, book and unchanged book state. The server rechecks the provider's canonical metadata and local canonical/alias conflicts. A conflicting row must be reviewed separately; this action does not merge or delete books.

A correction atomically replaces the work identity and its catalogue metadata, including default edition IDs. It keeps the Bookkeep row ID, requests and approval states, downloads, downloaded hashes, Grimmory/Audiobookshelf links and format availability. The stored ISBN remains the file's edition identifier, not an ISBN inferred from the new work. Existing request edition selections are retained as historical selections and shown in preview. Review those selections separately before further requests; a work correction does not reassign them to an edition of the new work.

Reviewed matches are stored in `hardcover_matches` with the admin and review time. Library sync respects them. Title/author and ISBN matches cannot replace a different canonical work. Uncertain new search candidates remain local and enter the review queue. Existing library links preserve identity without another lookup. Explicit collection matches are allowed; collections are not globally banned.

Canonical resolution follows forward aliases and reverse alias families. Missing, cyclic or excessive chains fail closed. When verification is unavailable, sync queues an unverified new candidate instead of assigning an identity. The queue keeps the current candidate and reason, not a full change history.

Migration 037 adds the review table. Startup reads `alembic_version` directly so an older tracked revision is upgraded rather than stamped to the newest head. Untracked legacy schemas are stamped only at the revision represented by their existing tables.

The October 2026 incidents involved title/author search returning collection records 1836489 and 1976891 for individual works 458307 and 748620. The earlier rehearsal used explicit slugs. Live API inspection found no canonical redirects connecting the wrong and correct works, and both collection records had `compilation=false`. Tests therefore protect identities independently of that flag and replay the actual mismatches.
