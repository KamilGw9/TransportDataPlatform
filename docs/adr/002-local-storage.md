# ADR 002: Local PostgreSQL and S3 storage

Status: accepted for local development

Date: 2026-09-29

## Context

Stage 2 of the [project plan](../project-plan.md) needs local storage for the
ingestion pipeline: PostgreSQL for records of what was fetched and processed,
and S3-compatible object storage for the original files.

MinIO Community is now archived. Its October 2025 security release is source-only,
so using a historical prebuilt server image would omit that release's fix.

## Decision

- Use one local Compose project with PostgreSQL 17 and a source-built, pinned
  MinIO release. Build the pinned `mc` client into the same image and reuse it
  for the initialization container; its historical registry image is unavailable.
- Keep PostgreSQL and S3 data in separate named volumes; bind host ports to
  loopback and keep credentials in ignored `.env`.
- Create only the four SQL schemas and the `mobility` bucket. Domain tables and
  collection come in the next stage.
- Fail startup if authenticated bucket creation fails. Make initialization safe
  to repeat. Do not mask a failure with a successful final shell command.
- Verify real SQL and S3 data across container recreation, with no volume reset.
- Treat MinIO as a local compatibility fixture, not a production hosting decision.
  Keep application access compatible with S3 to support a later replacement.

## Consequences

The first server build downloads Go dependencies and is slower and larger than
pulling a prebuilt image. Later starts reuse the image. Archive status means no
ongoing upstream maintenance; review object storage before a shared or cloud
deployment. Local admin credentials simplify the local setup but must
not be reused as a production application identity. No paid services are needed.

Sources: [MinIO archive status](https://github.com/minio/minio),
[security release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z),
[PostgreSQL official image](https://hub.docker.com/_/postgres).
