# Contributing to the HoodHaus maintenance fork

This repository is a maintenance fork of https://github.com/boludo00/bookkeep.
Keep fixes small, retain attribution, and review community patches before
reimplementing them.

## Branches and pull requests

- Branch from `develop`.
- Target pull requests explicitly at **mahood73/bookkeep**, base `develop`.
- Keep the upstream remote for fetching and comparing source. Upstream
  contributions are a separate, deliberate decision.
- This fork does not use upstream's automatic main-branch version bumping.

## Validation

The fork workflow runs backend tests on Python 3.11, matching the container
runtime, then builds the existing Dockerfile for linux/amd64 and linux/arm64.
Pull requests, develop pushes and default manual runs do not publish images.
They use read-only repository permissions and do not log in to a registry.

## Publishing a fork release

A push to the fork's `develop` branch runs tests, then builds and publishes
one multi-platform image and creates its GitHub release. It reserves a fresh
`v<base>-hoodhaus.<number>` tag for the exact source commit before building.
The base version is stored in `.github/fork-version.txt`.

Pull requests and default manual runs use a separate validation-only build.
Release runs skip that job and build once in the publishing job; the publishing
job depends directly on successful tests. A failed build creates no release and
may leave a reserved tag gap. Retries reserve a new tag instead of overwriting
an existing image. To recover a missed trigger, manually run the workflow on
`develop` with Publish enabled. Other branches cannot publish.

The only image destination is `ghcr.io/mahood73/bookkeep`. Each release gets
a new fork version tag, with the full source commit recorded in its labels and
GitHub release. The workflow records the
image digest for deployment. It does not publish `latest` or moving SHA tags, push to Docker Hub,
open pull requests, or deploy HoodHaus.

The publishing job alone has `contents: write` and `packages: write`, using the built-in
`GITHUB_TOKEN`. No Docker Hub credentials or personal token are required.
Do not provide upstream Docker Hub credentials to this fork.

Keep the initial package private while upstream licensing is unresolved.
Package visibility must be checked before any future publication. No project
licence grant was found during the initial source/history review; do not add
an assumed licence or remove upstream attribution.

## Deployment

HoodHaus deployment is a separate change to `arrs/bookkeep/compose.yaml` in
the HoodHaus repository. Pin a verified image digest and use the existing
Komodo workflow. Publication alone never updates the live service.
