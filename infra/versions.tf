terraform {
  required_version = ">= 1.10"

  # State lives in S3 (bucket created by infra/bootstrap). bucket and region come from
  # backend.hcl; credentials from AWS_PROFILE / the standard chain. Locking uses an S3 lock file
  # next to the state object (no DynamoDB). Each workspace gets its own object under env:/.
  backend "s3" {
    key          = "solar-map/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  # null falls back to the standard credential chain (env vars, default profile).
  profile = var.aws_profile

  default_tags {
    tags = {
      Project     = "solar-map"
      Environment = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}
