# HoodHaus fork releases

The workflow is restricted to `mahood73/bookkeep`. A push to `develop` runs the
backend and release-safeguard tests, then builds and publishes amd64 and arm64
images to `ghcr.io/mahood73/bookkeep`. Pull requests build without publishing.
There is no automatic homelab deployment: HoodHaus still pins a reviewed digest.

The base version lives in `.github/fork-version.txt`. Release builds reserve the
next `v<base>-hoodhaus.<number>` Git tag for the exact source commit before
publication. Existing upstream tags and other base versions are ignored. A
failed build can leave an unused tag; retries reserve another number instead of
reusing an image tag. The workflow publishes no `latest` or moving SHA tag, and
writes only to the fork's GHCR namespace. After image publication succeeds, it
creates a GitHub release with the immutable image reference.

To recover a missed trigger, dispatch the workflow on `develop` with `publish`
set to true. Manual dispatch defaults to validation only, and publication from
any other branch is rejected. Develop runs are serialized; PR runs cancel only
older validation runs for the same PR.

Runners use `ubuntu-24.04`. The Docker frontend builder uses
`node:24-bookworm-slim`, and action releases explicitly use the Node 24 runtime.
Major Node and OS changes are reviewed; patch updates remain available within
those selected lines.
