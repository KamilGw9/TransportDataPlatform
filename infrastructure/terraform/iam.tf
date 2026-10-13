data "aws_iam_policy_document" "host_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "urban-mobility-host"
  assume_role_policy = data.aws_iam_policy_document.host_assume_role.json
}

data "aws_iam_policy_document" "raw_access" {
  # Without ListBucket, S3 answers 403 instead of 404 for a missing key, and
  # upload_raw needs the 404 to know that it should upload.
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn]
  }

  # GetObject also covers HeadObject. Nothing on the host deletes RAW objects,
  # so the role cannot either.
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/*"]
  }
}

resource "aws_iam_role_policy" "raw_access" {
  name   = "raw-access"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.raw_access.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "host" {
  name = "urban-mobility-host"
  role = aws_iam_role.host.name
}
