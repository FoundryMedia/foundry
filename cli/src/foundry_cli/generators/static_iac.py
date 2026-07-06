"""Static-site IaC generator (``foundry generate static-iac``).

Emits a complete, self-contained OpenTofu stack for a ``static``-strategy
service: S3 bucket (OAC-only) + CloudFront + ACM cert (us-east-1) + Route53
aliases + a GitHub-OIDC runner role. The orchestrator's smart IaC step
(plan -> apply-on-change) applies it; CI never hand-edits it.

DRY rationale: web (foundryplatform.app), the wiki (foundry-dev.com), and the
hub were near-identical hand-copies. This generator is the single source of
that shape. Variation is data, not code:

  * ``www_domain != ""``  -> apex site: +www SAN, +301-redirect CloudFront
    function, +www DNS aliases. Empty -> plain subdomain site.
  * ``spa_fallback``      -> 403/404 -> /index.html (200) for client routing;
    false -> NO custom error responses (raw origin errors — a dedicated
    errorPage mode for doc sites with on-disk 404 pages is future work, see
    the wiki gap analysis in .claude/plans/).
  * ``csp_report_only``   -> a Content-Security-Policy (Report-Only) custom
    header on the response-headers policy; empty -> enforced safe headers only
    (HSTS / X-Content-Type-Options / X-Frame-Options / Referrer-Policy always
    ship). The policy is attached to the distribution in cloudfront.tf.

All variability lives in ``variables.tf`` defaults (manifest-derived) and
plan-time-known HCL conditionals — resource files are CONSTANT text, so every
generated stack is structurally identical and upgradeable by regeneration.
(Per the platform IaC rule: never gate count/for_each on computed values —
the gates here are input variables only.)

ORG-AGNOSTIC: nothing here hard-codes a company. Inputs come from the central
manifest: platform ``ci.state`` (bucket/region for remote state) + per-service
``deploy.iac`` (domain, hostedZoneId, region, bucket, stateKey, spaFallback,
wwwDomain, roleName) + the service's ``repository``.

Pure data -> {filename: content}. No I/O here; the command layer writes files.
"""

from __future__ import annotations

from dataclasses import dataclass

from foundry_cli.core.project.manifest import ProjectManifest


@dataclass(frozen=True)
class StaticSiteSpec:
    """Resolved inputs for one static-site stack (manifest -> defaults applied)."""

    service: str
    repo: str               # owner/repo
    repo_short: str         # repo name without owner
    platform_name: str      # tag value
    region: str
    domain: str
    www_domain: str         # "" = subdomain site (no redirect/SAN/aliases)
    hosted_zone_id: str
    bucket: str
    role_name: str
    spa_fallback: bool
    state_bucket: str
    state_key: str
    state_region: str
    stack_path: str
    deploy_branch: str              # branch whose OIDC ref the runner role trusts
    oidc_subjects: tuple[str, ...]  # GitHub OIDC sub claims trusted by the role
    csp_report_only: str            # optional Content-Security-Policy (Report-Only); "" = safe headers only


def resolve_spec(
    manifest: ProjectManifest, service_name: str, env: str = "prod"
) -> StaticSiteSpec:
    """Resolve a service's static-site spec from the central manifest.

    Defaults mirror the existing hand-written web stack so a regenerated web
    stack stays state-compatible: bucket ``<repo-short>-<service>``, state key
    ``<repo-short>-<service>/tofu.tfstate``, role ``<bucket>-tofu-runner``.
    """
    svc = manifest.services_config.get(service_name)
    if svc is None:
        raise ValueError(f"service '{service_name}' not found in {manifest.path}")
    if (svc.effective_strategy or "") != "static":
        raise ValueError(
            f"service '{service_name}' has strategy "
            f"'{svc.effective_strategy}' — static-iac only generates for 'static'."
        )
    iac = (svc.deploy.iac if svc.deploy else {}) or {}

    repo = svc.repository or ""
    if not repo and manifest.organization and manifest.repository:
        repo = f"{manifest.organization}/{manifest.repository}"
    if not repo or "/" not in repo:
        raise ValueError(
            f"service '{service_name}' needs a 'repository' (owner/repo) — the "
            "OIDC runner role trusts it."
        )
    repo_short = repo.split("/", 1)[1]

    domain = iac.get("domain")
    zone = iac.get("hostedZoneId")
    stack_path = iac.get("stackPath")
    if not domain or not zone or not stack_path:
        raise ValueError(
            f"service '{service_name}' deploy.iac needs domain, hostedZoneId, "
            "and stackPath for static-iac generation."
        )

    ci = manifest.data.get("ci") or {}
    state = ci.get("state") or {}
    state_bucket = state.get("bucket")
    if not state_bucket:
        raise ValueError(
            "manifest ci.state.bucket is required (S3 bucket for OpenTofu "
            "remote state, e.g. ci: { state: { bucket: ..., region: ... } })."
        )

    # `or`-defaults throughout: an explicit JSON null must fall back too —
    # .get(key, default) would return None and leak the string "None" into HCL.
    region = iac.get("region") or "us-east-1"
    bucket = iac.get("bucket") or f"{repo_short}-{service_name}"

    envs = manifest.resolve_environments(service_name)
    branch = envs[env].branch if env in envs else "main"

    # The role carries broad permissions (tofu apply), so the trust policy is
    # scoped to the deploy branch's ref by default — NOT repo:*:* (any branch/PR
    # of the repo could assume it). Override via deploy.iac.oidcSubjects for
    # repos that need more (e.g. an environment:* subject).
    subjects = tuple(iac.get("oidcSubjects") or [f"repo:{repo}:ref:refs/heads/{branch}"])

    return StaticSiteSpec(
        service=service_name,
        repo=repo,
        repo_short=repo_short,
        platform_name=manifest.name or "Platform",
        region=region,
        domain=domain,
        www_domain=iac.get("wwwDomain") or "",
        hosted_zone_id=zone,
        bucket=bucket,
        role_name=iac.get("roleName") or f"{bucket}-tofu-runner",
        spa_fallback=bool(iac.get("spaFallback", True)),
        state_bucket=state_bucket,
        state_key=iac.get("stateKey") or f"{repo_short}-{service_name}/tofu.tfstate",
        state_region=state.get("region") or region,
        stack_path=stack_path,
        deploy_branch=branch,
        oidc_subjects=subjects,
        # Report-Only CSP, per-site (the connect/script/style sources differ per app).
        # Empty -> the response-headers policy still ships the enforced safe headers.
        csp_report_only=iac.get("cspReportOnly") or "",
    )


def json_list(items: tuple[str, ...]) -> str:
    """Render a python tuple of strings as an HCL list literal."""
    return "[" + ", ".join(f'"{i}"' for i in items) + "]"


# ── file renderers ───────────────────────────────────────────────────────────
# Only backend.tf, providers.tf, and variables.tf interpolate manifest values
# (backends cannot reference variables). Everything else is constant HCL.


def _header(spec: StaticSiteSpec) -> str:
    return (
        "# ════════════════════════════════════════════════════════════════\n"
        "# GENERATED BY: foundry generate static-iac\n"
        f"# Service: {spec.service} ({spec.domain})  Repo: {spec.repo}\n"
        "# Regenerate: foundry generate static-iac --service "
        f"{spec.service}\n"
        "# Manual edits are overwritten on regeneration — change the manifest\n"
        "# (deploy.iac) instead; structural changes go in the CLI generator.\n"
        "# ════════════════════════════════════════════════════════════════\n\n"
    )


def render_backend(spec: StaticSiteSpec) -> str:
    return _header(spec) + f"""terraform {{
  required_version = ">= 1.10"

  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}

  backend "s3" {{
    bucket       = "{spec.state_bucket}"
    key          = "{spec.state_key}"
    region       = "{spec.state_region}"
    encrypt      = true
    use_lockfile = true
  }}
}}
"""


def render_providers(spec: StaticSiteSpec) -> str:
    tags = f"""    tags = {{
      Platform   = "{spec.platform_name}"
      Component  = "{spec.service}"
      ManagedBy  = "OpenTofu"
      Repository = "{spec.repo}"
    }}"""
    return _header(spec) + f"""# Regional provider + us-east-1 alias (CloudFront ACM certs MUST be us-east-1).

provider "aws" {{
  region = var.region

  default_tags {{
{tags}
  }}
}}

provider "aws" {{
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {{
{tags}
  }}
}}
"""


def render_variables(spec: StaticSiteSpec) -> str:
    return _header(spec) + f"""variable "region" {{
  type        = string
  description = "Primary AWS region for the site bucket."
  default     = "{spec.region}"
}}

variable "bucket_name" {{
  type        = string
  description = "S3 bucket holding the built static site. Globally unique."
  default     = "{spec.bucket}"
}}

variable "domain" {{
  type        = string
  description = "Domain that serves the site (must belong to the hosted zone)."
  default     = "{spec.domain}"
}}

variable "www_domain" {{
  type        = string
  description = "Optional www host that 301-redirects to the domain. Empty = subdomain site (no redirect)."
  default     = "{spec.www_domain}"
}}

variable "hosted_zone_id" {{
  type        = string
  description = "Route53 hosted zone ID for the domain."
  default     = "{spec.hosted_zone_id}"
}}

variable "github_repo" {{
  type        = string
  description = "owner/repo trusted by the CI OIDC role (GitHub Actions sub claim)."
  default     = "{spec.repo}"
}}

variable "role_name" {{
  type        = string
  description = "Name of the GitHub-OIDC runner role (tofu apply + publish)."
  default     = "{spec.role_name}"
}}

variable "spa_fallback" {{
  type        = bool
  description = "Serve /index.html (200) on 403/404 so a client-side router owns deep links. False = real error codes."
  default     = {"true" if spec.spa_fallback else "false"}
}}

variable "oidc_subjects" {{
  type        = list(string)
  description = "GitHub OIDC sub claims trusted to assume the runner role. Scoped to the deploy branch by default (the role can tofu-apply)."
  default     = {json_list(spec.oidc_subjects)}
}}
"""


def render_bucket(spec: StaticSiteSpec) -> str:
    return _header(spec) + """# ── Site bucket ───────────────────────────────────────────────
# Holds the built static site. CloudFront-only access via OAC; fully
# rebuildable by CI, so no versioning/lifecycle.

resource "aws_s3_bucket" "site" {
  bucket = var.bucket_name

  tags = {
    Name = var.bucket_name
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Lock down all public access. CloudFront OAC is the only reader.
resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bucket policy: only this CloudFront distribution (via OAC) can GetObject.
data "aws_iam_policy_document" "site_bucket" {
  statement {
    sid    = "AllowCloudFrontOACRead"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket.json
}
"""


def render_certificate(spec: StaticSiteSpec) -> str:
    return _header(spec) + """# ACM certificate for CloudFront — must be in us-east-1. DNS-validated.
# SANs include the www host only when one is configured.

resource "aws_acm_certificate" "site" {
  provider = aws.us_east_1

  domain_name               = var.domain
  subject_alternative_names = var.www_domain != "" ? [var.www_domain] : []
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = var.domain
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = var.hosted_zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "site" {
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
"""


def render_cloudfront(spec: StaticSiteSpec) -> str:
    return _header(spec) + """# ── Origin Access Control ─────────────────────────────────────
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.bucket_name}-oac"
  description                       = "OAC for ${var.bucket_name}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ── Viewer-request function: www -> apex 301 (apex sites only) ─
resource "aws_cloudfront_function" "router" {
  count   = var.www_domain != "" ? 1 : 0
  name    = "${var.bucket_name}-router"
  runtime = "cloudfront-js-2.0"
  comment = "${var.www_domain} -> ${var.domain} 301"
  publish = true
  code = templatefile("${path.module}/function.js.tftpl", {
    apex_host = var.domain
    www_host  = var.www_domain
  })
}

# ── CloudFront distribution ───────────────────────────────────
resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  comment             = "${var.bucket_name} (${var.domain})"
  price_class         = "PriceClass_100"
  default_root_object = "index.html"
  aliases             = compact([var.domain, var.www_domain])

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "${var.bucket_name}-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "${var.bucket_name}-s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    allowed_methods = ["GET", "HEAD"]
    cached_methods  = ["GET", "HEAD"]

    # AWS-managed CachingOptimized. Built assets are hash-named/immutable;
    # CI invalidates /* after each publish so index.html updates immediately.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    # Enforced security headers (+ optional report-only CSP). See response-headers.tf.
    # Applies on cache HIT and MISS, so no invalidation is needed.
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    dynamic "function_association" {
      for_each = var.www_domain != "" ? [1] : []
      content {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.router[0].arn
      }
    }
  }

  # SPA fallback: client-side routes are not real S3 keys; S3+OAC returns
  # 403 (and 404). Serve index.html with a 200 so the router takes over.
  # Disabled for doc sites that ship real error pages.
  dynamic "custom_error_response" {
    for_each = var.spa_fallback ? [403, 404] : []
    content {
      error_code            = custom_error_response.value
      response_code         = 200
      response_page_path    = "/index.html"
      error_caching_min_ttl = 10
    }
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
"""


def render_response_headers(spec: StaticSiteSpec) -> str:
    """CloudFront response-headers policy: enforced safe headers + optional CSP.

    HSTS / X-Content-Type-Options / X-Frame-Options / Referrer-Policy are ENFORCED
    on every response (constant, secure-by-default for any static site). A
    Content-Security-Policy is emitted in REPORT-ONLY mode ONLY when the manifest
    sets ``deploy.iac.cspReportOnly`` — report-only first so a bad policy can't
    break the SPA; flip the header name to enforce after reviewing violations.
    Attached to the distribution in cloudfront.tf (applies on cache hit + miss).
    """
    if spec.csp_report_only:
        # The CSP uses only single-quoted source keywords ('self' etc.), so it is
        # safe inside an HCL double-quoted string.
        csp_block = f'''

  custom_headers_config {{
    items {{
      header   = "Content-Security-Policy-Report-Only"
      value    = "{spec.csp_report_only}"
      override = true
    }}
  }}'''
        comment_csp = " + report-only CSP"
    else:
        csp_block = ""
        comment_csp = ""

    return _header(spec) + f"""# ── Security response-headers policy ──────────────────────────
# Enforced HSTS / X-Content-Type-Options / X-Frame-Options / Referrer-Policy on
# every response; optional report-only CSP when deploy.iac.cspReportOnly is set.
# A response-headers policy applies on cache HIT and MISS -> no invalidation.

resource "aws_cloudfront_response_headers_policy" "security" {{
  name    = "${{var.bucket_name}}-security-headers"
  comment = "Enforced HSTS/XFO/XCTO/Referrer{comment_csp} for ${{var.domain}}"

  security_headers_config {{
    strict_transport_security {{
      access_control_max_age_sec = 63072000 # 2 years
      include_subdomains         = true
      preload                    = true
      override                   = true
    }}

    content_type_options {{
      override = true
    }}

    frame_options {{
      frame_option = "DENY"
      override     = true
    }}

    referrer_policy {{
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }}
  }}{csp_block}
}}
"""


def render_dns(spec: StaticSiteSpec) -> str:
    return _header(spec) + """# Route53 aliases -> CloudFront (A + AAAA for the domain, +www when set).

locals {
  alias_hosts = compact([var.domain, var.www_domain])
  alias_records = merge([
    for host in local.alias_hosts : {
      "${host}_A"    = { name = host, type = "A" }
      "${host}_AAAA" = { name = host, type = "AAAA" }
    }
  ]...)
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
"""


def render_iam(spec: StaticSiteSpec) -> str:
    return _header(spec) + """# ── GitHub Actions OIDC runner role ──────────────────────────
# Lets the service repo's deploy workflow assume a role via short-lived OIDC
# tokens. Full tofu-in-CI: this role runs `tofu apply` AND publishes (s3 sync
# + CloudFront invalidation). Created on the FIRST local bootstrap apply;
# thereafter CI assumes it keylessly.
#
# TODO(security): replace AdministratorAccess with a least-privilege policy
# (this stack's S3 / CloudFront / ACM / Route53 / IAM surface) once stable.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "tofu_runner_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Branch-scoped by default: this role runs `tofu apply`, so an arbitrary
    # branch/PR workflow of the repo must NOT be able to assume it.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = var.oidc_subjects
    }
  }
}

resource "aws_iam_role" "tofu_runner" {
  name               = var.role_name
  description        = "GitHub OIDC role for ${var.github_repo} (tofu apply + publish)."
  assume_role_policy = data.aws_iam_policy_document.tofu_runner_trust.json

  tags = {
    Name = var.role_name
  }
}

resource "aws_iam_role_policy_attachment" "tofu_runner_admin" {
  role       = aws_iam_role.tofu_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
"""


def render_outputs(spec: StaticSiteSpec) -> str:
    return _header(spec) + """output "bucket_name" {
  description = "S3 bucket the deploy syncs the built site to."
  value       = aws_s3_bucket.site.id
}

output "distribution_id" {
  description = "CloudFront distribution ID the deploy invalidates."
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_domain" {
  description = "CloudFront domain (target of the Route53 aliases)."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "tofu_runner_role_arn" {
  description = "OIDC role ARN — the deploy.iac.roleArn for this service."
  value       = aws_iam_role.tofu_runner.arn
}

output "urls" {
  description = "Public URLs once DNS + cert propagate."
  value = concat(
    ["https://${var.domain}"],
    var.www_domain != "" ? ["https://${var.www_domain}"] : [],
  )
}
"""


_FUNCTION_TEMPLATE = """// CloudFront Function (viewer-request): canonical www -> apex 301.
// Templated by OpenTofu: apex_host and www_host injected at apply.
// Restricted JS runtime: ES5-style only (var, no template literals/arrows).

function handler(event) {
  var request = event.request;
  var host = request.headers.host ? request.headers.host.value : "";

  if (host === "${www_host}") {
    return {
      statusCode: 301,
      statusDescription: "Moved Permanently",
      headers: {
        location: { value: "https://${apex_host}" + request.uri }
      }
    };
  }

  return request;
}
"""


def generate_static_iac(
    manifest: ProjectManifest, service_name: str, env: str = "prod"
) -> tuple[StaticSiteSpec, dict[str, str]]:
    """Generate the full stack. Returns (spec, {filename: content}).

    ``function.js.tftpl`` is ALWAYS emitted: tofu evaluates templatefile()
    during the validation walk even when the referencing resource has
    count = 0, so a missing file fails `tofu validate`/`plan` outright
    (verified empirically). With www_domain unset the function resource is
    count-gated off and the template is inert.
    """
    spec = resolve_spec(manifest, service_name, env)
    files = {
        "backend.tf": render_backend(spec),
        "providers.tf": render_providers(spec),
        "variables.tf": render_variables(spec),
        "bucket.tf": render_bucket(spec),
        "certificate.tf": render_certificate(spec),
        "cloudfront.tf": render_cloudfront(spec),
        "response-headers.tf": render_response_headers(spec),
        "dns.tf": render_dns(spec),
        "iam.tf": render_iam(spec),
        "outputs.tf": render_outputs(spec),
        "function.js.tftpl": _FUNCTION_TEMPLATE,
    }
    return spec, files
