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
curl -fsSL -o $plugins/docker-compose \
  https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-aarch64
curl -fsSL -o $plugins/docker-buildx \
  https://github.com/docker/buildx/releases/download/v0.29.1/buildx-v0.29.1.linux-arm64
sha256sum --check <<EOF
d26373b19e89160546d15407516cc59f453030d9bc5b43ba7faf16f7b4980137  $plugins/docker-compose
50e85c4e290b698908421161c1aee069bcc5d4a65b7b7201bfac3a176b223a7e  $plugins/docker-buildx
EOF
chmod +x $plugins/docker-compose $plugins/docker-buildx
systemctl enable --now docker
