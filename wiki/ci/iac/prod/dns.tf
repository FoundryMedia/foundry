# Route53 aliases: apex + wiki subdomain -> CloudFront.

locals {
  alias_records = {
    apex_a    = { name = var.apex_domain, type = "A" }
    apex_aaaa = { name = var.apex_domain, type = "AAAA" }
    wiki_a    = { name = var.wiki_subdomain, type = "A" }
    wiki_aaaa = { name = var.wiki_subdomain, type = "AAAA" }
    www_a     = { name = var.www_domain, type = "A" }
    www_aaaa  = { name = var.www_domain, type = "AAAA" }
  }
}

resource "aws_route53_record" "site" {
  for_each = local.alias_records

  zone_id = var.hosted_zone_id
  name    = each.value.name
  type    = each.value.type

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
