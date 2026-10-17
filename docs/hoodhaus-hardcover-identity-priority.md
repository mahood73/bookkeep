# Known Hardcover identity during library import

A Want-to-read/list import already supplies the requested Hardcover work ID.
Previously, first Grimmory import could find that existing catalogue row, then
search by title and author again because the file lacked a Hardcover ID. A bad
search result entered the review queue even though the original ID was retained.
The dialog then offered that candidate instead of the known request identity.

The selected repair uses an existing catalogue ID before fuzzy discovery when
both title and author agree and the file supplies no explicit Hardcover ID.
Metadata is fetched by the known ID, without a title search. If that lookup
fails, existing catalogue description, page count, cover and ratings remain
available to metadata processing. Normal library linking continues with that ID.
An ISBN-only association with a different title or author does not qualify.
Explicit conflicting library IDs still pass through the canonical conflict
guard. Human-reviewed corrections remain protected.

This prevents new unnecessary review entries. It does not accept pending
candidates, clear historical review rows, change existing corrected identities,
or modify the final manual import-review process.

Regression coverage runs the real Hardcover list sync, first library sync and
pending-review API against disposable SQLite and fixture API responses. It
covers absent, matching and conflicting file IDs, plus the existing identity,
canonical-family, ISBN-conflict and reviewed-correction cases. The original
fixture failed by returning current ID 123 alongside wrong candidate 456.

The operator's six reported rows were already corrected before diagnosis.
Those historical rows were not replayed or changed. No live provider or library
was used to test this repair.
