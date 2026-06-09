output "bucket_name" {
  description = "S3 bucket the CI workflow syncs the built site to."
  value       = aws_s3_bucket.site.id
}

output "distribution_id" {
  description = "CloudFront distribution ID the CI workflow invalidates."
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_domain" {
  description = "CloudFront domain (target of the Route53 aliases)."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "tofu_runner_role_arn" {
  description = "OIDC role ARN — set as role-to-assume in .github/workflows/wiki.yml."
  value       = aws_iam_role.tofu_runner.arn
}

output "urls" {
  description = "Public URLs once DNS + cert propagate."
  value = {
    apex = "https://${var.apex_domain}"
    wiki = "https://${var.wiki_subdomain}"
  }
}
