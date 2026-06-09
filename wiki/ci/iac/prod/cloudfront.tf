# ── Origin Access Control ─────────────────────────────────────
# OAC lets CloudFront sign requests to the private S3 bucket without
# making the bucket public.

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.bucket_name}-oac"
  description                       = "OAC for ${var.bucket_name}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ── Viewer-request function ───────────────────────────────────
# Host-aware redirect (wiki.* -> docs) + clean-URL -> .html rewrite.

resource "aws_cloudfront_function" "router" {
  name    = "foundry-wiki-router"
  runtime = "cloudfront-js-2.0"
  comment = "wiki.* root redirect + clean-URL .html rewrite"
  publish = true
  code = templatefile("${path.module}/function.js.tftpl", {
    apex_host       = var.apex_domain
    wiki_host       = var.wiki_subdomain
    www_host        = var.www_domain
    redirect_target = var.redirect_target
  })
}

# ── CloudFront distribution ───────────────────────────────────
# One distribution, two aliases (apex + wiki). Everything served from the
# single S3 origin; the function handles routing.

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  comment             = "Foundry Wiki (${var.apex_domain})"
  price_class         = "PriceClass_100"
  default_root_object = "index.html"
  aliases             = [var.apex_domain, var.wiki_subdomain, var.www_domain]

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "foundry-wiki-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "foundry-wiki-s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    allowed_methods = ["GET", "HEAD"]
    cached_methods  = ["GET", "HEAD"]

    # AWS-managed CachingOptimized. _next/* assets are hash-named/immutable;
    # CI invalidates /* after each publish so HTML updates appear immediately.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.router.arn
    }
  }

  # Missing keys come back from S3+OAC as 403 (and 404). Serve the exported
  # 404 page. Scoped to client-not-found only — leave 5xx to surface normally.
  custom_error_response {
    error_code         = 403
    response_code      = 404
    response_page_path = "/404.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 404
    response_page_path = "/404.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.site.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  depends_on = [aws_acm_certificate_validation.site]

  tags = {
    Name = "${var.bucket_name}-cdn"
  }
}
