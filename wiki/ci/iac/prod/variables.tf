variable "region" {
  type        = string
  description = "Primary AWS region for the site bucket."
  default     = "us-east-2"
}

variable "bucket_name" {
  type        = string
  description = <<-EOT
    S3 bucket holding the built static site (Next.js export). Globally unique;
    qualified with the platform name since the wiki is a singleton.
  EOT
  default     = "foundry-wiki-site"
}

variable "apex_domain" {
  type        = string
  description = "Apex domain that serves the wiki landing (must match the hosted zone)."
  default     = "foundry-dev.com"
}

variable "wiki_subdomain" {
  type        = string
  description = "Subdomain that serves the wiki and auto-redirects / to the docs entry point."
  default     = "wiki.foundry-dev.com"
}

variable "www_domain" {
  type        = string
  description = "Conventional www host; 301-redirects to the apex (preserving the path)."
  default     = "www.foundry-dev.com"
}

variable "hosted_zone_id" {
  type        = string
  description = "Route53 hosted zone ID for foundry-dev.com (account 561493797917)."
  default     = "Z09230743M1R7JZB95R4V"
}

variable "redirect_target" {
  type        = string
  description = <<-EOT
    Path the wiki_subdomain redirects to from "/", skipping the apex landing.
    Defaults to the first Getting Started doc. Switch to /docs/quick-start if preferred.
  EOT
  default     = "/docs/installation"
}

variable "github_repo" {
  type        = string
  description = "owner/repo trusted by the CI OIDC role (GitHub Actions sub claim)."
  default     = "FoundryMedia/foundry"
}
