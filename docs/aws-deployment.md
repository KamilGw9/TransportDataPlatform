# Deployment on the AWS host

The AWS host runs the same Compose services as the laptop, on one EC2 Spot
instance described in [ADR 007](adr/007-aws-hosting.md). The differences are in
`compose.aws.yaml`: RAW goes to S3 with the credentials of the instance role
instead of MinIO, and PostgreSQL keeps its data on a separate EBS volume mounted
at `/data`. The deployment is manual: a shell on the instance through SSM,
`git pull` and `make`.

On the laptop this needs Terraform 1.14 or newer, AWS CLI v2 with credentials
for the account and the Session Manager plugin for the AWS CLI. The commands
below assume that `AWS_PROFILE` selects those credentials.

## Create the resources

```bash
cd infrastructure/terraform
terraform init
terraform apply
```

`terraform.tfvars` sets `alert_email`, the address of the budget alerts; it is
ignored by Git, like the Terraform state, which exists only on the laptop. The
outputs `host_instance_id` and `raw_bucket` are used below.

On its first boot the instance runs `host-init.sh`: it creates a file system on
the data volume if the volume is empty, mounts it at `/data`, adds 2 GB of swap
and installs Docker with the Compose and buildx plugins, Git and Make. Docker
starts only after `/data` is mounted, so PostgreSQL cannot start on an empty
directory of the root volume. `cloud-init status` on the instance reports
`done` when the script has finished and `error` when it has failed; its output
is in `/var/log/cloud-init-output.log`.

The script runs once per instance, and Terraform ignores changes to it, because
applying them would stop and start the instance for nothing. A change to
`host-init.sh` therefore applies to the next new instance; on the running one it
has to be repeated by hand. The instance created on 2026-10-13 lacks two such
changes: Make was installed by hand, and the Docker drop-in that waits for
`/data` is still missing. It is added as root with:

```bash
mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=/data\n' \
  >/etc/systemd/system/docker.service.d/data-mount.conf
systemctl daemon-reload
systemctl show docker -p RequiresMountsFor
```

## Open a shell

From `infrastructure/terraform` on the laptop:

```bash
aws ssm start-session --target "$(terraform output -raw host_instance_id)"
sudo -i
```

The security group allows no inbound traffic; the SSM agent on the instance
opens the session from the inside. The commands below run as root.

## First deployment

The repository is private, so the instance clones it with a read-only deploy
key generated on it:

```bash
ssh-keygen -t ed25519 -N '' -f /root/.ssh/github_deploy
printf 'Host github.com\n  IdentityFile /root/.ssh/github_deploy\n' >>/root/.ssh/config
ssh-keyscan -t ed25519 github.com >>/root/.ssh/known_hosts
ssh-keygen -lf /root/.ssh/known_hosts
cat /root/.ssh/github_deploy.pub
```

The fingerprint must match the one GitHub publishes for its ED25519 key. The
public key is added in the repository settings under Deploy keys, without
write access. The key stays on the root volume, so a new instance needs a new
one.

```bash
git clone git@github.com:KamilGw9/TransportDataPlatform.git /data/urban-mobility
cd /data/urban-mobility
make setup
```

The repository lives on the data volume because `.env` does: the PostgreSQL
password in it must match the database on the same volume, and a replacement
instance would otherwise generate a new one. In `.env`, set:

```bash
S3_BUCKET=<raw_bucket output>
S3_REGION=eu-central-1
COMPOSE_FILE=compose.yaml:compose.aws.yaml
```

Compose reads `COMPOSE_FILE` from `.env` by itself, so every `docker compose`
and `make` command in this directory uses both files, and `make up` skips MinIO.
Then start the services:

```bash
make collect
make airflow
```

The first build of the images takes a few minutes.

## Check that it works

Recent fetch attempts, with status `stored` or `unchanged` and no errors:

```bash
docker compose exec postgres psql -U mobility -d mobility -c \
  "SELECT fetched_at, source_id, status, error FROM metadata.fetch_attempt ORDER BY fetched_at DESC LIMIT 10"
aws s3 ls "s3://<raw_bucket>/raw/gtfs_rt/" --recursive | tail -3
```

The states of the latest DAG runs, read from the `airflow` database, because
the Airflow CLI prints a warning before its output:

```bash
docker compose exec postgres psql -U mobility -d airflow -c \
  "SELECT dag_id, state, start_date FROM dag_run ORDER BY start_date DESC LIMIT 10"
```

The Airflow UI listens only on the loopback address of the instance. A port
forwarding session should make it available at `http://127.0.0.1:8080` on the
laptop, but this has not been tried yet:

```bash
aws ssm start-session --target "$(terraform output -raw host_instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=8080,localPortNumber=8080
```

## Update

```bash
cd /data/urban-mobility
git pull
make collect
make airflow
```

`make up`, which both run first, applies new migrations; `--build` rebuilds the
images with the new code, DAGs and dbt models.

## Stop and start

```bash
aws ec2 stop-instances --instance-ids <host_instance_id>
aws ec2 start-instances --instance-ids <host_instance_id>
```

Stopping the instance disables its Spot request, so AWS does not start it again
by itself. A start sent within about a minute of the stop fails with
`IncorrectSpotRequestState`. After a start, every service starts again through
`restart: unless-stopped` and collection resumes. A stopped instance costs only
its volumes and snapshots.

## Limitations

- The data collected on the laptop has not been moved to the host yet.
- Nothing reports a failed run or an interruption of the Spot instance.
- The Terraform state, `.env` and the deploy key each exist in one place only.
