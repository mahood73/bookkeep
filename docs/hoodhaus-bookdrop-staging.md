# Bookdrop staging and consumer cleanup

Related tracking: [HoodHaus issue #57](https://gitlab.com/mahood73/hoodhaus/-/issues/57).

Bookkeep stages completed downloads for another application to consume. That
consumer needs write and execute permission on each containing directory to
delete a staged file. A writable intake root alone does not provide that access
inside copied subdirectories.

## Candidate behavior

The staging method attempts hardlinks per file and falls back to an ordinary
copy for that file if linking fails. This permits a tree containing both linked
and copied files, including a later link failure after earlier successes.

New destination directories retain copied modes with owner read, write and
execute access added. The staging process owns those directories. Source
directories and source/staged file modes and ownership are not normalized.
In particular, changing a hardlinked file's metadata would change its original
download inode too; this change never does that.

This requires an appropriate staging-process identity. It does not grant an
unrelated consumer write access to a root-owned destination. Existing staged
directories retain their existing behavior; this is not a repair operation for
an existing backlog. Original source readability is still required.

## HoodHaus adoption proposal

After reviewing and merging this fork change, obtain the published release's
exact source revision and image digest. Prepare a separate HoodHaus MR that
pins that release and sets only the Bookkeep application service's Compose
`user` to `1000:1000`, matching Grimmory. Retain the database and Redis service
identities. Do not deploy the identity change with the older image, whose
directory hardlink fallback and directory-mode behavior remain defective.

Before deployment:

- Check effective access to download-client output and both staging mounts,
  including ownership, modes, ACLs and same-filesystem hardlink behavior.
  Follow HoodHaus's production access policy for evidence unavailable through
  its inspection MCP. An older host-access approval does not carry forward.
- Obtain a recoverable pre-upgrade backup and rehearse the image's normal
  entrypoint/migrations against an isolated database copy, with disposable
  mounts and outbound integrations disabled. Do not infer migration safety
  from a new database or a schema stamped at current heads.
- Test authenticated UI/API use, a direct download fixture, existing client
  output, ebook and audiobook staging, copying, successful hardlinks, and
  fallback copying. Verify original source bytes and metadata remain intact.
- With a disposable Grimmory target, verify import and source-file cleanup for
  bare and nested EPUBs, then absence of rediscovery on its next periodic scan.
  A permissions-only unlink probe is not a Grimmory import test.
- Validate recreation and scheduled/background work, and update the affected
  HoodHaus hardening inventory with the actual results.

Mark performs the separately approved Komodo sync/deployment. Afterward use
inspection for service evidence and operator confirmation for the real
import/cleanup and next-scan result. Keep #57 open until acceptance is complete.

## Verification so far

The added regressions exercise the real orchestrator with a disposable database
and real files. Only the external download handler and induced link errors are
substituted. They verify cleanup under the same identity, read-only source
directory modes, per-file EXDEV/EPERM fallback after an earlier successful link,
and preservation of original bytes, ownership and modes. Run on Linux as a
non-root user to exercise real unlink permissions, not root bypass behavior.

Initial reproduction used the pinned HoodHaus image in local Linux containers.
Startup, health, UI shell, a database-backed public endpoint and the actual
direct-transfer method passed as UID 1000 with synthetic current-schema state.
An empty PostgreSQL database failed with `NoSuchTableError: books` as both root
and UID 1000. These checks do not validate database-copy migrations,
authenticated workflows or Grimmory itself.

## Rollback

Before adoption, record the previous image digest and application identity and
retain the pre-upgrade database backup. Restore the reviewed prior image and
Compose identity and redeploy through Komodo if rollback is required. If the
release includes database migrations, assess schema compatibility and restore
the backup if required; an image downgrade alone may not be safe.

An identity rollback does not revert ownership of already staged directories.
Inspect any backlog separately before an approved targeted repair. Never
recursively change download-source permissions or ownership, and never chmod
hardlinked file inodes as a cleanup workaround.
