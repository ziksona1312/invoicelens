# ADR 0004: SeaweedFS instead of MinIO for local S3 storage

Status: accepted (2026-11-20)

## Context

The original plan used MinIO, the usual S3 stand-in for local stacks. When phase 2 started,
MinIO's community edition was no longer a safe choice: it stopped publishing Docker images and
binaries in October 2025, `minio/minio` was removed from Docker Hub, and the GitHub repository
was archived in April 2026. The last published image contains known vulnerabilities and will not
be patched.

Candidates that keep the S3 API, so the application code does not change:

| Option | License | Why not / why |
| --- | --- | --- |
| Pinned old MinIO image or a third-party mirror | AGPL-3.0 | Unmaintained, known CVEs, unofficial publisher |
| RustFS | Apache-2.0 | Closest drop-in, but still pre-1.0 when this was decided |
| Garage | AGPL-3.0 | Needs a layout/key setup step before first use |
| **SeaweedFS** | Apache-2.0 | Mature (since 2015), official image, one container with `server -s3` |

## Decision

Use SeaweedFS (`chrislusf/seaweedfs`, pinned to a version tag) running master, volume, filer and
S3 gateway in one container. Credentials come from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`,
the same variables boto3 reads in the application.

The application talks only to the S3 API through boto3, with the endpoint in `S3_ENDPOINT_URL`.
Tests use moto's in-memory S3, so they need no storage server at all.

## Consequences

- Switching to RustFS, Garage or real AWS S3 later is a configuration change, not a code change.
- SeaweedFS has no MinIO-style console; buckets and objects are inspected with any S3 client.
- Lesson recorded: pin image versions, and check that a dependency is still maintained before
  building on it.
