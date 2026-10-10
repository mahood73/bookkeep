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

Publishing requires a fork tag of the form `v1.6.2-hoodhaus.1`. Push the
tag to trigger publication, or manually run the workflow against that tag
with the Publish input enabled. The input defaults to false, and selecting a
branch cannot publish even with the input enabled. The tagged commit must
already be included in `develop`.
Tests and the validation build must pass before publication.

The only image destination is `ghcr.io/mahood73/bookkeep`. Each release gets
its fork version tag and a full source commit tag. The workflow records the
image digest for deployment. It does not publish `latest`, push to Docker Hub,
create Git tags, open pull requests, or deploy HoodHaus.

The publishing job alone has `packages: write`, using the built-in
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
