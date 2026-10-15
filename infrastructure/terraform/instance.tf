data "aws_vpc" "default" {
  default = true
}

# No inbound rules: shell access and the Airflow UI tunnel go through SSM,
# which the agent on the instance opens from the inside.
resource "aws_security_group" "host" {
  name        = "urban-mobility-host"
  description = "No inbound access to the pipeline host"
  vpc_id      = data.aws_vpc.default.id
}

# Terraform removes the egress rule that AWS adds to a new security group.
# The host needs the feeds, SSM, S3, GitHub and the image and package
# registries, so all outbound traffic is allowed.
resource "aws_vpc_security_group_egress_rule" "host_all" {
  security_group_id = aws_security_group.host.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# The data volume can be attached only in its own zone, so the instance stays
# in one zone for good.
data "aws_subnet" "host" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "eu-central-1a"
  default_for_az    = true
}

data "aws_ssm_parameter" "al2023_x86_64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "host" {
  # The free plan of the account allows only a few instance types, and this
  # is the cheapest of them with 4 GB.
  instance_type          = "c7i-flex.large"
  ami                    = data.aws_ssm_parameter.al2023_x86_64.insecure_value
  subnet_id              = data.aws_subnet.host.id
  vpc_security_group_ids = [aws_security_group.host.id]
  iam_instance_profile   = aws_iam_instance_profile.host.name

  user_data = templatefile("${path.module}/host-init.sh", {
    volume_serial = replace(aws_ebs_volume.postgres.id, "-", "")
  })

  # Without a maximum price, AWS caps the Spot price at the on-demand price.
  instance_market_options {
    market_type = "spot"

    spot_options {
      spot_instance_type             = "persistent"
      instance_interruption_behavior = "stop"
    }
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
  }

  # Containers on the Docker bridge network are one hop further from the
  # metadata service than the host, and with the default limit of 1 they
  # would not get the role credentials.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  tags = {
    Name = "urban-mobility-host"
  }

  # The parameter points to a new AMI every few weeks, which would otherwise
  # replace the instance on the next apply.
  lifecycle {
    ignore_changes = [ami]
  }
}

output "host_instance_id" {
  value = aws_instance.host.id
}

# The arrival predictions of hours that left the staging window exist only in
# this database, so Terraform refuses to destroy the volume.
resource "aws_ebs_volume" "postgres" {
  availability_zone = data.aws_subnet.host.availability_zone
  type              = "gp3"
  size              = 30

  tags = {
    Name = "urban-mobility-postgres"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Stopping the instance first lets PostgreSQL shut down cleanly before its
# volume is detached, for example when the instance is replaced.
resource "aws_volume_attachment" "postgres" {
  device_name                    = "/dev/sdf"
  volume_id                      = aws_ebs_volume.postgres.id
  instance_id                    = aws_instance.host.id
  stop_instance_before_detaching = true
}
