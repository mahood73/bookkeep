# Jobs UI dispatch and UTC timestamps

Diagnosis reproduced two existing faults in release `.8`:

- `sync_hardcover_lists` was registered in APScheduler and shown in the Jobs UI,
  but absent from the manual route's separate function map. The route moved the
  periodic next-run time before returning HTTP 500. For mapped jobs it both
  rescheduled APScheduler and queued its own background task, dispatching twice.
- The scheduler stripped a BST offset and the API appended `Z`. A real scheduled
  instant of 17 October 2026 17:05 Europe/London became 17:05Z instead of 16:05Z.
  The January control passed because London was then on UTC.

## Selected repair

The scheduler definitions now supply the manual job inventory and both callers
resolve task functions through the same lazy registry. The internal download-state
job remains excluded from the manual UI. The route validates the function before
tracking or writing a run. One tracked background task performs each manual click.
It retains the existing run ID/status interface and does not alter the periodic
schedule, matching the promise already displayed on the Jobs page.

Scheduler-generated times convert to aware UTC before persistence. API job and
run timestamps emit one UTC designator. Interval triggers explicitly use UTC.
The conversion covers scheduled completions, initial schedule persistence,
rescheduling, active scheduler responses and saved-state fallback.

Legacy naive database values keep the existing API interpretation as UTC. The
repair does not guess offsets for historical values or run a timestamp migration.
It does not change saved intervals, enabled settings, credentials or list contents.
Manual dispatch still uses the existing process-local background/run tracking;
this change does not add durable or distributed job execution.

## Verification

Regression tests use actual APScheduler jobs, the Jobs API functions and disposable
SQLite. Workload fixtures prevent live syncs or downloads. They prove one manual
execution with an unchanged periodic deadline, error responses without schedule
or history writes, run completion/failure reporting, BST/GMT conversion and
database fallback after every scheduler persistence path. The original Hardcover
manual-run test failed with HTTP 500; the original BST fixture was exactly one
hour late. No live job was triggered to test the repair.
