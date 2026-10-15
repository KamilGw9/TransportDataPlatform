#!/bin/bash
# Runs once, on the first boot of each new instance. Rendered by Terraform's
# templatefile, so bash variables are written without braces.
set -euo pipefail

# Terraform attaches the volume only after the instance has started.
postgres_device=/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${volume_serial}
until [ -e "$postgres_device" ]; do
  sleep 5
done

# A replacement instance must find the existing database, so only an empty
# volume gets a file system.
if ! blkid "$postgres_device"; then
  mkfs.xfs "$postgres_device"
fi

# With nofail, the instance still boots without the volume and can be
# reached through SSM to find out why.
mkdir -p /data
echo "UUID=$(blkid -s UUID -o value "$postgres_device") /data xfs defaults,nofail 0 2" >>/etc/fstab
mount /data

# 2 GB of swap as a margin for dbt builds (ADR 007).
dd if=/dev/zero of=/swapfile bs=1M count=2048
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile none swap defaults 0 0" >>/etc/fstab

# Amazon Linux packages Docker without the Compose and buildx plugins, and
# Compose builds the images with buildx. The versions match the local ones.
dnf install -y docker git
plugins=/usr/local/lib/docker/cli-plugins
mkdir -p $plugins
# The script does not run again after a failure, so a GitHub or DNS error
# right after boot is retried instead of leaving the host without Docker.
curl -fsSL --retry 5 --retry-all-errors -o $plugins/docker-compose \
  https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64
curl -fsSL --retry 5 --retry-all-errors -o $plugins/docker-buildx \
  https://github.com/docker/buildx/releases/download/v0.29.1/buildx-v0.29.1.linux-amd64
sha256sum --check <<EOF
dba9d98e1ba5bfe11d88c99b9bd32fc4a0624a30fafe68eea34d61a3e42fd372  $plugins/docker-compose
7d2d7d6d4680aa349614965aaa33ccec43f1a9a21e908a5ce4cb6adfa5ad5141  $plugins/docker-buildx
EOF
chmod +x $plugins/docker-compose $plugins/docker-buildx

# nofail lets the boot go on without /data, so without this Docker could start
# first and PostgreSQL would initialise an empty database on the root volume.
mkdir -p /etc/systemd/system/docker.service.d
cat >/etc/systemd/system/docker.service.d/data-mount.conf <<EOF
[Unit]
RequiresMountsFor=/data
EOF
systemctl daemon-reload
systemctl enable --now docker
