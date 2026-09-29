FROM golang:1.24.8-bookworm@sha256:4ed690d6649d63c312b99a6120025ec79ce3b542968a37da53d6236c7c61a848 AS build

# This source-only release includes the October 2025 security fix.
ENV CGO_ENABLED=0
RUN go install -trimpath -ldflags="-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z" \
    github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z
RUN go install -trimpath -ldflags="-s -w" \
    github.com/minio/mc@RELEASE.2025-08-13T08-35-41Z

FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /go/bin/minio /usr/local/bin/minio
COPY --from=build /go/bin/mc /usr/local/bin/mc
COPY --from=build /go/pkg/mod/github.com/minio/minio@*/LICENSE /licenses/minio-LICENSE
COPY --from=build /go/pkg/mod/github.com/minio/mc@*/LICENSE /licenses/mc/
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
