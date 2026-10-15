# ADR 007: One EC2 instance for collection and model builds

Status: accepted

Date: 2026-10-12

## Context

The collectors, loaders and model builds run in Compose on a laptop. Between
2026-10-03 and 2026-10-06 the laptop's sleep stopped the collectors for 17 to
23 hours each night, so the data covers afternoons and evenings only and none
of it crosses midnight. Realtime snapshots cannot be fetched again later, so
every hour of sleep is lost for good. Validating the service date inference and
the punctuality figures needs at least a week of continuous collection.

On 2026-10-12 the database took 4.7 GB and the RAW archive in MinIO 0.9 GB,
growing by about 0.3 GB a day. On 2026-10-11, with each container limited so
that all of them except MinIO fit into 1.7 GB, a run of `refresh_models`
passed, but `dbt build` took 188 s instead of 123 s, and PostgreSQL and the
Airflow scheduler stayed at their limits and used swap.

The AWS account is on the free plan: 100 USD of credits until 2027-04-12, when
the account is closed unless it moves to a paid plan. Moving to a paid plan is
not intended, and the project needs the host for about two months. The free
plan launches only a few instance types; in `eu-central-1`, the ones with at
least 4 GB are c7i-flex.large and m7i-flex.large.

Options considered, with prices for `eu-central-1` (Frankfurt) on 2026-10-13,
before VAT:

- Keep the laptop and disable sleep. It costs nothing, but the laptop is not on
  all the time and is already short of memory with Airflow running.
- Managed services: RDS for PostgreSQL, MWAA for Airflow, ECS for the
  collectors. The smallest RDS instance has 1 GB of memory, too little for the
  dbt builds, and MWAA costs hundreds of dollars a month. Each service would
  also replace a part of the Compose setup that works.
- One EC2 instance running the existing Compose setup. A t4g.medium (2 ARM
  vCPUs, 4 GB) would cost about 16 USD a month as a Spot instance, but the free
  plan rejects it. A c7i-flex.large (2 x86 vCPUs, 4 GB) costs about 71 USD a
  month on demand or about 33 USD as a Spot instance. A t4g.small (2 GB) costs
  about 5 USD as a Spot instance and 14 USD on demand, but the test above
  leaves it no margin for a growing database or a longer build, and running
  out of memory would stop the collectors as well.
- On the instance, RAW either stays in MinIO on an EBS volume or moves to S3.
  MinIO keeps the setup identical to the local one, but the archive would then
  share the fate of one volume. S3 costs cents a month at this size.

## Decision

- Run the Compose services on one c7i-flex.large Spot instance in
  `eu-central-1a`, with Amazon Linux 2023 and 2 GB of swap as a margin for dbt
  builds, while the free plan credits last. The Spot
  request is persistent and stops the instance on interruption, so it starts
  again with its disks when capacity returns. The maximum price is the
  on-demand price.
- Keep the PostgreSQL data on a separate gp3 volume, so the instance can be
  replaced without losing the database. Snapshot that volume daily and keep 7
  snapshots. A snapshot of a running database is crash-consistent, which
  PostgreSQL recovers from as after a power loss.
- Store RAW in an S3 bucket with public access blocked, under the same object
  keys as in MinIO. The services get S3 credentials from the instance role
  instead of keys in `.env`; locally, MinIO stays.
- Open no inbound ports. Shell access and the tunnel to the Airflow UI go
  through SSM Session Manager, so there is no SSH key to manage.
- The instance clones the private repository with a read-only deploy key
  generated on it, and builds the images itself. A deployment is `git pull`
  and `make` in an SSM session; there is no automatic deployment.
- `make setup` generates the passwords on the instance, so `.env` never leaves
  it.
- Describe every AWS resource in Terraform under `infrastructure/terraform/`,
  including an AWS Budgets alert at 60 USD. The state stays on the laptop,
  outside Git.
- Do not move the data collected on the laptop. The host keeps the database
  of its test run on 2026-10-13 and collects continuously from 2026-10-15; the
  laptop keeps the first week, from which the figures in the project status
  were computed. That week covers no night, so it adds little to what a week
  on the host gives. Moving it would need the RAW objects copied to S3 and the
  database moved with `pg_dump`, because the loaders find snapshots through
  `metadata.fetch_attempt` and the arrival predictions of hours that left the
  staging window exist only in the database.

## Consequences

Expected cost is about 44 USD a month before VAT: 33 for the instance, 5 for
50 GB of gp3, 4 for the public IPv4 address, about 1 each for snapshots and
S3. With the 23% VAT that the budget counts, it is about 54 USD. Spot prices
change, and the budget alert reports a forecast above 60 USD. The credits last
between 1.8 and 2.3 months, depending on whether they also cover the VAT, so
with the VAT they run out a few days before the two months the project needs.
The data has to be copied out of AWS before they run out, or it goes with the
account.

Collection no longer depends on the laptop. An interruption of the Spot
instance stops collection until it starts again, and nothing reports such a
gap, as before. If interruptions turn out to be frequent, switching to
on demand is a one-line change, but at about 80 USD a month the credits would
last little more than a month. The data of the first week and the data from
the host are in separate databases, so no figure covers both.

The production setup differs from the local one in S3 and in how the services
get credentials, so S3 access has to be checked on the instance as well. The
instance runs unattended, so the missing alerts for failed runs matter more
than on the laptop. The Terraform state exists only on the laptop; losing it
means importing the resources by hand. The Kafka services planned later will
not fit into 4 GB alongside the current ones, so the instance size and budget
have to be revisited then.
