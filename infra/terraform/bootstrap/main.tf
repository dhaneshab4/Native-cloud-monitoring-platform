# Chicken-and-egg layer: the S3 bucket and lock table that hold everyone else's
# state cannot themselves live in remote state, so this one stack keeps its
# state locally and is applied once, by hand.
#
#   cd infra/terraform/bootstrap
#   terraform init && terraform apply
#
# The outputs go into envs/dev/backend.tf.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "cloud-native-monitoring"
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}

variable "region" {
  description = "AWS region for the state backend"
  type        = string
  default     = "eu-west-1"
}

variable "state_bucket" {
  description = "Globally unique bucket name for Terraform state"
  type        = string
  default     = "dhaneshab4-tfstate-cloud-native-monitoring"
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket

  # State files are the keys to the estate. Losing this bucket to a stray
  # `terraform destroy` would be worse than any resource it tracks.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 native locking (use_lockfile) is now the recommended path, but DynamoDB is
# still what most estates run and what interviewers ask about, so both are wired.
resource "aws_dynamodb_table" "lock" {
  name         = "terraform-state-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

output "state_bucket" {
  description = "Put this in envs/*/backend.tf"
  value       = aws_s3_bucket.state.id
}

output "lock_table" {
  value = aws_dynamodb_table.lock.name
}
