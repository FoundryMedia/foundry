# ── GitHub Actions OIDC integration ───────────────────────────
# Lets the FoundryMedia/foundry repo's wiki workflow assume an IAM role via
# short-lived OIDC tokens — no AWS keys in GitHub Secrets.
#
# Full tofu-in-CI: this role runs `tofu apply` AND publishes (s3 sync +
# CloudFront invalidation), so it needs broad perms. Created on the FIRST
# local bootstrap apply (PlatformAdmin); thereafter CI assumes it keylessly.
#
# TODO(security): replace AdministratorAccess with a least-privilege policy
# (this stack's S3 / CloudFront / ACM / Route53 / IAM surface) once stable.
# Mirrors the foundry-iac fgs-prod-tofu-runner precedent + its same TODO.

# Account-wide OIDC provider singleton — already exists, reference it.
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

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "tofu_runner" {
  name               = "foundry-wiki-tofu-runner"
  description        = "GitHub OIDC role for the foundry wiki workflow (tofu apply + publish)."
  assume_role_policy = data.aws_iam_policy_document.tofu_runner_trust.json

  tags = {
    Name = "foundry-wiki-tofu-runner"
  }
}

resource "aws_iam_role_policy_attachment" "tofu_runner_admin" {
  role       = aws_iam_role.tofu_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
