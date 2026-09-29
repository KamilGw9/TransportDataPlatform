# Local PostgreSQL and S3 storage

This stage supplies storage for the future ingestion pipeline. It does not download
GTFS or create transport-domain tables. Requirements: Docker with Compose v2,
GNU Make, Python 3, and uv for Python quality checks. Run commands from the repository
root. Docker Desktop users must enable integration with their WSL distribution.

## Start and stop

```bash
make setup
make up
make ps
```

`make setup` fills missing settings in `.env` and generates missing passwords. It
preserves existing nonempty values, including your PostgreSQL password. `.env` is
ignored by Git and restricted to its owner. `.env.example` contains no secrets.
Compose reads this file; Make never evaluates it as shell code.

The first build compiles the pinned MinIO source release and can take several
minutes, with substantially more disk and memory use than subsequent starts.
`make up` waits for PostgreSQL and MinIO to become healthy, then runs bucket
initialization in the foreground. A failed initialization makes the command fail.
Repeated initialization preserves existing buckets and objects.

```bash
make logs
make down
make up
```

`make down` removes containers and the Compose network but retains named volumes.
`docker compose down -v` deletes database and object data; it is not part of the
normal workflow. Volumes are not backups. The Compose project is `urban-mobility`;
changing that name selects different volumes rather than moving existing data.

## Connections

| Service | From WSL / host | From another container on the Compose network |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | `postgres:5432` |
| S3 API | `http://127.0.0.1:9000` | `http://minio:9000` |
| MinIO console | `http://127.0.0.1:9001` | `http://minio:9001` |

Host ports can be changed with `POSTGRES_PORT`, `MINIO_API_PORT` and
`MINIO_CONSOLE_PORT` in `.env`; internal ports stay the same. Host ports bind only
to loopback. Use local `.env` values for credentials; do not paste them into logs.

PostgreSQL defaults to database/user `mobility`. `make postgres` opens psql using
the configured values. Schemas:

- `metadata`: future fetch, file and processing records;
- `staging`: future input tables;
- `core`: future normalized transport models;
- `marts`: future analytical outputs.

The initial SQL only runs on a new empty PostgreSQL volume. Changes to init SQL or
`POSTGRES_PASSWORD` do not migrate an existing database. Use explicit SQL migrations
and password changes once data exists.

S3 defaults to bucket `mobility`, region `us-east-1`, path-style addressing.
For the future local Python collector, the access key is `MINIO_ROOT_USER`, the
secret key is `MINIO_ROOT_PASSWORD`, and the endpoint is the host S3 URL above.
These are development administrator credentials; application-scoped credentials
are required before sharing or deploying this environment.

## Verify persistence

```bash
make check-infra
```

This integration check starts the stack, checks all four schemas, authenticates
to PostgreSQL over TCP, writes a uniquely named SQL table and S3 object, recreates
both service containers, runs bucket initialization again, and checks both values.
It briefly interrupts this project's database and storage. It retains all volumes
and removes only its own test table/object afterward. Cleanup after a service
failure is best-effort; remaining probes use `infra_` names or
`_infrastructure_checks/` object keys.

Expected result: `PASS: all schemas exist; SQL row and S3 object survived container recreation.`

## Troubleshooting

- Connection to `docker.sock` denied: check Docker Desktop WSL integration or
  Docker permissions for the current terminal.
- Port already allocated: change the corresponding host port in `.env` and run
  `make up` again.
- Unhealthy service: inspect `docker compose logs --tail=100 postgres minio`.
- Bucket initialization failed: check MinIO health and credentials, then rerun
  `docker compose run --rm --no-deps minio-init`.
- Schema missing on an existing database: inspect the database before applying
  `infrastructure/docker/postgres/init.sql`; do not reset the volume to repair it.

## MinIO lifecycle

MinIO Community is archived and no longer maintained. We retain it only as the
local S3-compatible learning environment agreed in the project plan. The server
is compiled from `RELEASE.2025-10-15T17-29-55Z`, which includes the last published
security fix, rather than using an older prebuilt server image. This does not make
the archived release suitable for a new public production deployment.

The same image contains `mc`, compiled from `RELEASE.2025-08-13T08-35-41Z`, for
bucket initialization and storage checks. This avoids dependency on unavailable
historical client images in external registries. Both base images are pinned by
digest in the Dockerfile.

See [ADR 002](adr/002-local-storage.md), [upstream status](https://github.com/minio/minio)
and [release notes](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z).
The ingestion code should use the S3 API so that the backing service can be replaced
independently of data processing.
