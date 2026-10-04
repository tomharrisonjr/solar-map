terraform {
  required_version = ">= 1.9"

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
