"""ST-10: the static-iac generator must never emit an AdministratorAccess runner.

The runner role every generated stack ships is PowerUserAccess + an inline IAM
policy scoped to the stack's own ``<bucket>-*`` roles/policies, with explicit
denies on admin-policy attachment and on rewriting its own role. Pinned here so
the debt cannot regrow through regeneration.
"""

from __future__ import annotations

import re

from foundry_cli.generators.static_iac import StaticSiteSpec, render_iam


def _spec(**overrides) -> StaticSiteSpec:
    base = dict(
        service="hub",
        repo="FoundryMedia/foundry-hub",
        repo_short="foundry-hub",
        platform_name="Foundry",
        region="us-east-2",
        domain="hub.example.app",
        www_domain="",
        hosted_zone_id="Z0000000000000000000",
        bucket="foundry-hub",
        role_name="foundry-hub-tofu-runner",
        spa_fallback=True,
        state_bucket="state-bucket",
        state_key="foundry-hub/tofu.tfstate",
        state_region="us-east-2",
        stack_path="ci/iac/prod",
        deploy_branch="main",
        oidc_subjects=("repo:FoundryMedia/foundry-hub:ref:refs/heads/main",),
        csp_report_only="",
        extra_providers=(),
    )
    base.update(overrides)
    return StaticSiteSpec(**base)


def test_runner_is_not_administrator():
    out = render_iam(_spec())
    # The only place AdministratorAccess may appear is inside the deny list —
    # never as an attachment.
    assert 'policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"' not in out
    assert 'resource "aws_iam_role_policy_attachment" "tofu_runner_admin"' not in out
    assert 'policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"' in out
    assert 'resource "aws_iam_role_policy_attachment" "tofu_runner_poweruser"' in out
    assert 'resource "aws_iam_role_policy" "tofu_runner_iam_scoped"' in out


def test_iam_is_scoped_to_the_stack_prefix():
    out = render_iam(_spec())
    assert '"arn:aws:iam::*:role/${var.bucket_name}-*"' in out
    assert '"arn:aws:iam::*:policy/${var.bucket_name}-*"' in out
    assert '"arn:aws:iam::*:instance-profile/${var.bucket_name}-*"' in out
    # A roleName override outside the bucket prefix must still let the runner
    # refresh its own role, so the own ARN is listed explicitly.
    assert "aws_iam_role.tofu_runner.arn," in out
    assert '"iam:GetOpenIDConnectProvider"' in out


def test_escalation_and_self_modification_are_denied():
    out = render_iam(_spec())
    assert re.search(r'sid\s+=\s+"DenyAdminPolicyAttach"', out)
    assert '"arn:aws:iam::aws:policy/AdministratorAccess"' in out
    assert '"arn:aws:iam::aws:policy/IAMFullAccess"' in out
    assert 'variable = "iam:PolicyARN"' in out
    assert re.search(r'sid\s+=\s+"DenySelfModification"', out)
    for action in (
        "iam:UpdateAssumeRolePolicy",
        "iam:PutRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRole",
    ):
        assert f'"{action}"' in out
    assert "resources = [aws_iam_role.tofu_runner.arn]" in out


def test_trust_still_pinned_to_manifest_subjects():
    out = render_iam(_spec())
    assert "values   = var.oidc_subjects" in out
    assert 'variable = "token.actions.githubusercontent.com:sub"' in out
    assert "TODO(security)" not in out
