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
