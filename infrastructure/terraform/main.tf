terraform {
  required_version = ">= 1.14"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"

  # Cost Explorer can then separate this project's costs from the rest of the
  # account.
  default_tags {
    tags = {
      Project = "urban-mobility"
    }
  }
}
