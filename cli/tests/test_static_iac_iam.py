"""ST-10 / ADR-0008: the static-iac generator must never emit an AdministratorAccess runner.

The runner role every generated stack ships is PowerUserAccess + an inline IAM
policy scoped to the stack's own ``<bucket>-*`` roles/policies, a permissions
boundary every created role must carry, and explicit denies on admin-policy
attachment, boundary tampering, and rewriting its own role. Pinned here so the
debt cannot regrow through regeneration.
"""

from __future__ import annotations

import re

from foundry_cli.generators.static_iac import StaticSiteSpec, render_iam, render_outputs


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


def _sid(out: str, sid: str) -> bool:
    return re.search(rf'sid\s+=\s+"{sid}"', out) is not None


def test_runner_is_not_administrator():
    out = render_iam(_spec())
    # The only place AdministratorAccess may appear is inside the deny list —
    # never as an attachment.
    assert 'policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"' not in out
    assert 'resource "aws_iam_role_policy_attachment" "tofu_runner_admin"' not in out
    assert 'policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"' in out
    assert 'resource "aws_iam_role_policy_attachment" "tofu_runner_poweruser"' in out
    assert 'resource "aws_iam_role_policy" "tofu_runner_iam_scoped"' in out
    assert "TODO(security)" not in out


def test_iam_is_scoped_to_the_stack_prefix():
    out = render_iam(_spec())
    assert '"arn:aws:iam::*:role/${var.bucket_name}-*"' in out
    assert '"arn:aws:iam::*:policy/${var.bucket_name}-*"' in out
    assert '"arn:aws:iam::*:instance-profile/${var.bucket_name}-*"' in out
    # A roleName override outside the bucket prefix must still let the runner
    # refresh its own role, so the own ARN is listed explicitly.
    assert "aws_iam_role.tofu_runner.arn," in out
    assert '"iam:GetOpenIDConnectProvider"' in out
    # No unconditional iam:* on roles any more — role grants are gated below.
    assert not re.search(r'actions\s+=\s+\["iam:\*"\]\s+resources\s+=\s+\[\s*"arn:aws:iam::\*:role/', out)


def test_permissions_boundary_caps_created_roles():
    out = render_iam(_spec())
    assert 'resource "aws_iam_policy" "runner_boundary"' in out
    assert 'name        = "${var.bucket_name}-ci-runner-boundary"' in out
    assert 'not_actions = ["iam:*", "organizations:*", "account:*"]' in out
    assert _sid(out, "CeilingPassPrefixedRoles")
    # Grants require the boundary on the role.
    assert _sid(out, "ScopedRoleGrantsRequireBoundary")
    grants = out[out.index('sid    = "ScopedRoleGrantsRequireBoundary"'):]
    grants = grants[: grants.index("}\n  }\n")]
    for action in ("iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:PutRolePermissionsBoundary"):
        assert f'"{action}"' in grants
    assert 'variable = "iam:PermissionsBoundary"' in grants
    assert "values   = [aws_iam_policy.runner_boundary.arn]" in grants
    # The runner cannot raise the ceiling or take it off a role.
    assert _sid(out, "DenyBoundaryTamper")
    assert '"iam:CreatePolicyVersion"' in out and '"iam:SetDefaultPolicyVersion"' in out
    assert _sid(out, "DenyBoundaryRemoval")
    assert '"iam:DeleteRolePermissionsBoundary"' in out


def test_escalation_and_self_modification_are_denied():
    out = render_iam(_spec())
    assert _sid(out, "DenyAdminPolicyAttach")
    assert '"arn:aws:iam::aws:policy/AdministratorAccess"' in out
    assert '"arn:aws:iam::aws:policy/IAMFullAccess"' in out
    assert 'variable = "iam:PolicyARN"' in out
    assert _sid(out, "DenySelfModification")
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


def test_boundary_arn_is_exported_for_hand_added_roles():
    out = render_outputs(_spec())
    assert 'output "runner_boundary_arn"' in out
    assert "aws_iam_policy.runner_boundary.arn" in out
