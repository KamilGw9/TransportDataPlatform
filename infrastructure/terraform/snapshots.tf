data "aws_iam_policy_document" "dlm_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name               = "urban-mobility-snapshots"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume_role.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

# Snapshots of the running database are crash-consistent, which PostgreSQL
# recovers from as after a power loss (ADR 007).
resource "aws_dlm_lifecycle_policy" "postgres" {
  description        = "Daily snapshots of the PostgreSQL volume"
  execution_role_arn = aws_iam_role.dlm.arn

  policy_details {
    resource_types = ["VOLUME"]
    target_tags = {
      Name = aws_ebs_volume.postgres.tags["Name"]
    }

    schedule {
      name      = "daily"
      copy_tags = true

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }

      retain_rule {
        count = 7
      }
    }
  }
}
