# Foundry Wiki — provider configuration.
# Regional aws provider + us-east-1 alias (CloudFront ACM certs MUST live in us-east-1).

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Platform   = "FoundryWiki"
      Component  = "static-site"
      ManagedBy  = "OpenTofu"
      Repository = "FoundryMedia/foundry"
    }
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Platform   = "FoundryWiki"
      Component  = "static-site"
      ManagedBy  = "OpenTofu"
      Repository = "FoundryMedia/foundry"
    }
  }
}
