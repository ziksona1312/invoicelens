# ADR 0005: CI/CD and supply-chain security

Status: accepted (2026-11-25)

## Context

Phase 3 publishes a Docker image and makes `main` safe to depend on. While planning it, the
scanner we picked had itself been attacked: on 2026-03-19 stolen credentials were used to
force-push 76 of 77 tags of `aquasecurity/trivy-action` to credential-stealing code and to publish
a malicious Trivy release (CVE-2026-33634, GHSA-69fq-xp46-6x23). Every workflow that referenced
the action by tag ran the attacker's code. A CI pipeline is part of the attack surface.

## Decision

- **Pin every third-party action to a full commit SHA**, with the version as a comment
  (`uses: actions/checkout@<40-char sha> # v7.0.1`). A tag can be moved; a commit cannot.
- **Dependabot** opens weekly pull requests for GitHub Actions (it updates the SHA and the
  comment), pip, the Dockerfile base image, docker-compose images and pre-commit hooks. Nothing
  is updated without passing CI.
- **Least privilege.** Workflows default to `contents: read`; only the release job gets
  `packages: write`. `actions/checkout` runs with `persist-credentials: false`.
- **Downloaded tools are verified.** gitleaks is fetched from its release and checked against the
  published SHA-256 before it runs.
- **Image scanning with Trivy** on every pull request: a full HIGH/CRITICAL report for reading,
  and a gate that fails only on CRITICAL vulnerabilities that already have a fix. Failing on
  every HIGH, or on issues with no fix, would block work on things we cannot change.
- **Releases.** Pushing a tag `vX.Y.Z` builds the image, scans it, and only if the gate passes
  pushes it to `ghcr.io/ziksona1312/invoicelens` with tags `X.Y.Z`, `X.Y`, `latest` and the short
  commit SHA, plus an SBOM and build provenance attestation.
- **Protected `main`.** Changes arrive through pull requests; `test`, `docker` and
  `secrets-scan` must pass; force-push and deletion are blocked.
- **mypy** joins ruff in CI, so type errors are caught before review.

## Consequences

- SHA pins are unreadable on their own, which is why the version comment and Dependabot matter.
- The Trivy gate can turn red without any change on our side when a new CVE is published for the
  base image. That is intended: the fix is a Dependabot base-image bump or a rebuild.
- GHCR is free for public images. The package starts private and is made public once in its
  settings, so the image can be pulled without logging in (used by Terraform in phase 5).
