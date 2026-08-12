# Populate from the outputs of infra/terraform/bootstrap, then:
#   terraform init -reconfigure
#
# Left commented so `terraform init` works locally — and so CI can run
# `fmt`/`validate` on a pull request without needing AWS credentials at all.
#
# terraform {
#   backend "s3" {
#     bucket         = "dhaneshab4-tfstate-cloud-native-monitoring"
#     key            = "envs/dev/terraform.tfstate"
#     region         = "eu-west-1"
#     dynamodb_table = "terraform-state-lock"
#     encrypt        = true
#   }
# }
