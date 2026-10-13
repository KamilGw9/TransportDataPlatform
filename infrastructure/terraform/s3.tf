data "aws_caller_identity" "current" {}

# Bucket names are global, so the account ID keeps this one unique.
resource "aws_s3_bucket" "raw" {
  bucket = "urban-mobility-raw-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Realtime snapshots cannot be downloaded again, so an object deleted by
# mistake must stay recoverable. Objects are never rewritten, so versions cost
# nothing until something is deleted.
resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

output "raw_bucket" {
  value = aws_s3_bucket.raw.bucket
}
