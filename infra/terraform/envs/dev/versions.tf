terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# No kubernetes or helm provider on purpose. Terraform owns the infrastructure;
# Argo CD owns everything running on it. Configuring a kubernetes provider from
# this module's own outputs also breaks the first apply, because the cluster it
# needs to authenticate against does not exist yet.

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "cloud-native-monitoring"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repository  = "github.com/dhaneshab4/cloud-native-monitoring-platform"
    }
  }
}

