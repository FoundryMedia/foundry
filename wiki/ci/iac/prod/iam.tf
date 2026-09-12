# ── GitHub Actions OIDC integration ───────────────────────────
# Lets the FoundryMedia/foundry repo's wiki workflow assume an IAM role via
# short-lived OIDC tokens — no AWS keys in GitHub Secrets.
#
# Trust is pinned to the release branch ONLY (StringEquals on the sub claim):
# PR runs get no AWS credentials at all — the workflow's PR path is
# validate/build-verify only. The role runs `tofu apply` AND publishes
# (s3 sync + CloudFront invalidation) for release pushes / dispatches.
#
# Permissions (2026-09-07, extended 2026-09-12 for ADR-0008):
#   * PowerUserAccess (everything except IAM / Organizations / Account).
#   * A scoped inline IAM policy: reads/trust/lifecycle of this stack's own
#     foundry-wiki-* roles; anything that GRANTS a role permissions only when
#     the role carries the permissions boundary below; iam:* on foundry-wiki-*
#     policies + instance profiles; the OIDC provider read.
#   * Explicit denies: attaching an AWS-managed admin policy anywhere, editing
#     or deleting the boundary policy, removing the boundary from a role, and
#     rewriting THIS role's own trust / policies / boundary / existence.
#   * The permissions boundary (`foundry-wiki-ci-runner-boundary`) caps every
#     role this stack creates at the runner's own non-IAM reach.
#
# Changes to THIS file must be applied locally with PlatformAdmin (never via
# CI): DenySelfModification / DenyBoundaryTamper refuse them from the runner,
# and a CI self-apply could otherwise detach its own policy mid-run and strand
# the role.

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

# ── Permissions boundary for every role this stack creates ───────────────────
data "aws_iam_policy_document" "runner_boundary" {
  statement {
    sid         = "CeilingEverythingExceptIam"
    effect      = "Allow"
    not_actions = ["iam:*", "organizations:*", "account:*"]
    resources   = ["*"]
  }

  statement {
    sid       = "CeilingPassPrefixedRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::*:role/foundry-wiki-*"]
  }

  statement {
    sid    = "CeilingIamReadsAndServiceLinked"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:ListRoles",
      "iam:GetInstanceProfile",
      "iam:ListInstanceProfilesForRole",
      "iam:CreateServiceLinkedRole",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "runner_boundary" {
  name        = "foundry-wiki-ci-runner-boundary"
  description = "Permissions boundary every role created by the foundry-wiki CI runner must carry (ADR-0008). Ceiling = everything except IAM, plus PassRole of foundry-wiki-* roles."
  policy      = data.aws_iam_policy_document.runner_boundary.json
}

data "aws_iam_policy_document" "tofu_runner_iam_scoped" {
  statement {
    sid    = "ScopedRoleReadsTrustAndLifecycle"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListRoleTags",
      "iam:ListInstanceProfilesForRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
      "iam:DeleteRole",
      "iam:PassRole",
    ]
    resources = [
      "arn:aws:iam::*:role/foundry-wiki-*",
      aws_iam_role.tofu_runner.arn,
    ]
  }

  statement {
    sid    = "ScopedRoleGrantsRequireBoundary"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePermissionsBoundary",
    ]
    resources = ["arn:aws:iam::*:role/foundry-wiki-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.runner_boundary.arn]
    }
  }

  statement {
    sid     = "ScopedPoliciesAndInstanceProfiles"
    effect  = "Allow"
    actions = ["iam:*"]
    resources = [
      "arn:aws:iam::*:policy/foundry-wiki-*",
      "arn:aws:iam::*:instance-profile/foundry-wiki-*",
    ]
  }

  statement {
    sid       = "ReadOidcProvider"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  statement {
    sid       = "DenyAdminPolicyAttach"
    effect    = "Deny"
    actions   = ["iam:AttachRolePolicy", "iam:AttachUserPolicy", "iam:AttachGroupPolicy"]
    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values = [
        "arn:aws:iam::aws:policy/AdministratorAccess",
        "arn:aws:iam::aws:policy/PowerUserAccess",
        "arn:aws:iam::aws:policy/IAMFullAccess",
      ]
    }
  }

  statement {
    sid    = "DenyBoundaryTamper"
    effect = "Deny"
    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
    ]
    resources = [aws_iam_policy.runner_boundary.arn]
  }

  statement {
    sid       = "DenyBoundaryRemoval"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["arn:aws:iam::*:role/foundry-wiki-*"]
  }

  statement {
    sid    = "DenySelfModification"
    effect = "Deny"
    actions = [
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePermissionsBoundary",
      "iam:DeleteRolePermissionsBoundary",
      "iam:DeleteRole",
    ]
    resources = [aws_iam_role.tofu_runner.arn]
  }
}

resource "aws_iam_role_policy" "tofu_runner_iam_scoped" {
  name   = "foundry-wiki-tofu-runner-iam-scoped"
  role   = aws_iam_role.tofu_runner.id
  policy = data.aws_iam_policy_document.tofu_runner_iam_scoped.json
}

output "runner_boundary_arn" {
  description = "Permissions boundary every hand-added role in this stack must carry (ADR-0008)."
  value       = aws_iam_policy.runner_boundary.arn
}
