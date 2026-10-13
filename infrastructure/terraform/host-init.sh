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
