# ── GitHub Actions OIDC integration ───────────────────────────
# Lets the FoundryMedia/foundry repo's wiki workflow assume an IAM role via
# short-lived OIDC tokens — no AWS keys in GitHub Secrets.
#
# Trust is pinned to the release branch ONLY (StringEquals on the sub claim):
# PR runs get no AWS credentials at all — the workflow's PR path is
# validate/build-verify only. The role runs `tofu apply` AND publishes
# (s3 sync + CloudFront invalidation) for release pushes / dispatches.
#
# Permissions: PowerUserAccess (everything except IAM) + a scoped inline IAM
# policy limited to this stack's own foundry-wiki-* role/policies and reading
# the OIDC provider. Changes to THIS file must be applied locally with
# PlatformAdmin (never via CI): a CI self-apply can detach its own policy
# mid-run and strand the role.

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

    # Release branch only. The workflow job must NOT reference a GitHub
    # Environment — an environment-scoped job presents sub
    # "repo:<repo>:environment:<name>" instead of the ref form and would
    # fail this condition.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/release"]
    }
  }
}

resource "aws_iam_role" "tofu_runner" {
  name               = "foundry-wiki-tofu-runner"
  description        = "GitHub OIDC role for the foundry wiki workflow (tofu apply + publish, release branch only)."
  assume_role_policy = data.aws_iam_policy_document.tofu_runner_trust.json

  tags = {
    Name = "foundry-wiki-tofu-runner"
  }
}

# Everything except IAM. The stack's surface (S3, CloudFront, ACM, Route53)
# is fully covered; IAM is granted separately, scoped to this stack's own
# resources.
resource "aws_iam_role_policy_attachment" "tofu_runner_poweruser" {
  role       = aws_iam_role.tofu_runner.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "tofu_runner_iam_scoped" {
  statement {
    sid     = "ScopedIamOnWikiRunner"
    effect  = "Allow"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::*:role/foundry-wiki-*",
      "arn:aws:iam::*:policy/foundry-wiki-*",
    ]
  }

  statement {
    sid       = "ReadOidcProvider"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "tofu_runner_iam_scoped" {
  name   = "foundry-wiki-tofu-runner-iam-scoped"
  role   = aws_iam_role.tofu_runner.id
  policy = data.aws_iam_policy_document.tofu_runner_iam_scoped.json
}
