# Remote state. Reuses the platform-admin state bucket (account 561493797917)
# with a wiki-specific key, so no new bucket / no chicken-and-egg on first run.
# The bucket already exists (created by foundry-iac):
#   aws s3 mb s3://fgs-prod-iac-state --region us-east-2
#   aws s3api put-bucket-versioning --bucket fgs-prod-iac-state \
#     --versioning-configuration Status=Enabled

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket       = "fgs-prod-iac-state"
    key          = "wiki/tofu.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}
