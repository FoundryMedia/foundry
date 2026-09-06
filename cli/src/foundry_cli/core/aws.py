"""AWS CLI integration for Foundry CLI.

Provides credential detection and AWS API calls by shelling out to the
``aws`` CLI.  Foundry never stores AWS credentials — it uses whatever
the developer (or CI runner) has configured locally:

- ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` environment variables
- ``AWS_PROFILE`` environment variable or ``~/.aws/credentials`` profile
- AWS SSO (``aws sso login``)
- EC2 instance metadata / ECS task role (in CI)
- ``aws configure`` defaults

Resolution is handled entirely by the AWS CLI itself — Foundry just
calls it and reads the output.

Examples::

    from foundry_cli.core.aws import resolve_caller_identity, resolve_hosted_zone_id

    identity = resolve_caller_identity()
    print(identity.account_id)  # "561493797917"

    zone_id = resolve_hosted_zone_id("example.com", region="us-east-2")
    print(zone_id)  # "Z0123456789EXAMPLE"
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any

from foundry_cli.core.errors import FoundryError

logger = logging.getLogger(__name__)

_CLI_TIMEOUT = 15  # seconds


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass(frozen=True)
class AWSCallerIdentity:
    """Result of ``aws sts get-caller-identity``."""

    account_id: str
    arn: str
    user_id: str


@dataclass(frozen=True)
class AWSCredentialStatus:
    """Summary of the detected AWS credential state."""

    authenticated: bool
    account_id: str | None
    arn: str | None
    source: str  # e.g. "aws-cli", "none"
    error: str | None = None


# ------------------------------------------------------------------
# Low-level CLI runner
# ------------------------------------------------------------------


def _run_aws(
    *args: str,
    region: str | None = None,
) -> dict[str, Any] | list[Any] | str:
    """Run an ``aws`` CLI command and return parsed JSON output.

    Args:
        *args: AWS CLI arguments (e.g., ``"sts"``, ``"get-caller-identity"``).
        region: Optional region override (``--region``).

    Returns:
        Parsed JSON from stdout.

    Raises:
        FoundryError: If the ``aws`` CLI is not installed, times out,
            or returns a non-zero exit code.
    """
    cmd = ["aws", *args, "--output", "json"]
    if region:
        cmd.extend(["--region", region])

    logger.debug("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT,
        )
    except FileNotFoundError:
        raise FoundryError(
            "AWS CLI is not installed or not in PATH.\n"
            "  Install: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html\n"
            "  Then run: aws configure"
        )
    except subprocess.TimeoutExpired:
        raise FoundryError(
            f"AWS CLI timed out after {_CLI_TIMEOUT}s.\n"
            "  Check your network connection and AWS credentials."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()

        # Common error patterns → friendly messages
        if "ExpiredToken" in stderr or "InvalidClientTokenId" in stderr:
            raise FoundryError(
                "AWS credentials have expired.\n"
                "  Run: aws sso login  (or refresh your credentials)"
            )
        if "NoCredentialProviders" in stderr or "Unable to locate credentials" in stderr:
            raise FoundryError(
                "No AWS credentials found.\n"
                "  Foundry uses your local AWS CLI credentials.\n"
                "  Set up with one of:\n"
                "    • aws configure          (access key)\n"
                "    • aws sso login           (SSO)\n"
                "    • AWS_PROFILE env var     (named profile)\n"
                "    • AWS_ACCESS_KEY_ID env var"
            )
        raise FoundryError(f"AWS CLI error: {stderr}")

    stdout = result.stdout.strip()
    if not stdout:
        return {}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        # Some commands return plain text
        return stdout


# ------------------------------------------------------------------
# Identity & credential detection
# ------------------------------------------------------------------


def resolve_caller_identity(region: str | None = None) -> AWSCallerIdentity:
    """Resolve the current AWS caller identity.

    Equivalent to ``aws sts get-caller-identity``.  Uses whatever
    credentials are configured locally.

    Returns:
        An ``AWSCallerIdentity`` with account_id, arn, and user_id.

    Raises:
        FoundryError: If no credentials are configured or they are expired.
    """
    data = _run_aws("sts", "get-caller-identity", region=region)
    if not isinstance(data, dict):
        raise FoundryError("Unexpected response from aws sts get-caller-identity")

    return AWSCallerIdentity(
        account_id=data["Account"],
        arn=data["Arn"],
        user_id=data["UserId"],
    )


def detect_aws_credentials(region: str | None = None) -> AWSCredentialStatus:
    """Detect whether valid AWS credentials are available.

    Non-throwing — returns a status object indicating success or failure.
    Used by ``foundry config --show`` to display toolchain status.
    """
    try:
        identity = resolve_caller_identity(region=region)
        return AWSCredentialStatus(
            authenticated=True,
            account_id=identity.account_id,
            arn=identity.arn,
            source="aws-cli",
        )
    except FoundryError as exc:
        return AWSCredentialStatus(
            authenticated=False,
            account_id=None,
            arn=None,
            source="none",
            error=str(exc),
        )


# ------------------------------------------------------------------
# Route53 — hosted zone lookup by domain name
# ------------------------------------------------------------------


def resolve_hosted_zone_id(
    domain_name: str,
    region: str | None = None,
) -> str:
    """Look up a Route53 hosted zone ID by domain name.

    Equivalent to::

        aws route53 list-hosted-zones-by-name \\
            --dns-name example.com \\
            --max-items 1

    Args:
        domain_name: The domain name (e.g., ``example.com``).
        region: Optional region override.

    Returns:
        The hosted zone ID (e.g., ``Z0123456789EXAMPLE``).

    Raises:
        FoundryError: If no matching zone is found.
    """
    # Route53 is a global service but the CLI still needs a region context
    data = _run_aws(
        "route53", "list-hosted-zones-by-name",
        "--dns-name", domain_name,
        "--max-items", "1",
        region=region,
    )
    if not isinstance(data, dict):
        raise FoundryError(f"Unexpected response from Route53 API for domain '{domain_name}'")

    zones = data.get("HostedZones", [])
    if not zones:
        raise FoundryError(
            f"No Route53 hosted zone found for domain '{domain_name}'.\n"
            "  Ensure the domain is configured in Route53."
        )

    # Verify the zone matches the requested domain
    zone = zones[0]
    zone_name = zone["Name"].rstrip(".")
    if zone_name != domain_name.rstrip("."):
        raise FoundryError(
            f"Route53 returned zone '{zone_name}' but expected '{domain_name}'.\n"
            "  Ensure the domain has a hosted zone in Route53."
        )

    # Zone ID comes back as "/hostedzone/Z0123456789EXAMPLE"
    raw_id = zone["Id"]
    return raw_id.split("/")[-1]


# ------------------------------------------------------------------
# Secrets Manager — read/write secrets
# ------------------------------------------------------------------


def resolve_instance_public_ip(
    tag_name: str,
    region: str | None = None,
) -> str:
    """Resolve the public IP of a running EC2 instance by its Name tag.

    Used by the dev-run tunnel autowire (e.g. a bastion host whose IP changes
    across stop/start cycles).
    """
    data = _run_aws(
        "ec2", "describe-instances",
        "--filters",
        f"Name=tag:Name,Values={tag_name}",
        "Name=instance-state-name,Values=running",
        "--query", "Reservations[0].Instances[0].PublicIpAddress",
        region=region,
    )
    if not isinstance(data, str) or not data:
        raise FoundryError(
            f"No running EC2 instance found with tag:Name={tag_name}"
            + (f" in {region}" if region else "")
            + ".\n  Check the instance is running and your AWS profile targets the right account/region."
        )
    return data


def get_secret_value(
    secret_id: str,
    region: str | None = None,
) -> str:
    """Read a secret value from AWS Secrets Manager.

    Args:
        secret_id: The secret name or ARN.
        region: Optional region override.

    Returns:
        The secret string value.
    """
    data = _run_aws(
        "secretsmanager", "get-secret-value",
        "--secret-id", secret_id,
        region=region,
    )
    if not isinstance(data, dict):
        raise FoundryError(f"Unexpected response reading secret '{secret_id}'")

    return data.get("SecretString", "")


def get_secret_json(
    secret_id: str,
    region: str | None = None,
) -> dict[str, Any]:
    """Read a JSON secret from AWS Secrets Manager.

    Args:
        secret_id: The secret name or ARN.
        region: Optional region override.

    Returns:
        Parsed JSON dict from the secret value.
    """
    raw = get_secret_value(secret_id, region=region)
    # Strip UTF-8 BOM if present (can sneak in from editors/copy-paste)
    if raw.startswith("\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise FoundryError(
                f"Secret '{secret_id}' is not a JSON object (got {type(parsed).__name__})"
            )
        return parsed
    except json.JSONDecodeError as exc:
        raise FoundryError(
            f"Secret '{secret_id}' is not valid JSON: {exc}"
        ) from exc


def put_secret_value(
    secret_id: str,
    value: str,
    region: str | None = None,
) -> None:
    """Write a secret value to AWS Secrets Manager.

    Creates or updates the secret. Used by ``foundry generate tfvars --push``
    to upload generated tfvars for CI/CD consumption.

    Args:
        secret_id: The secret name or ARN.
        value: The secret string to store.
        region: Optional region override.
    """
    _run_aws(
        "secretsmanager", "put-secret-value",
        "--secret-id", secret_id,
        "--secret-string", value,
        region=region,
    )


# ------------------------------------------------------------------
# IP Whitelist — read from Secrets Manager
# ------------------------------------------------------------------


def resolve_ip_whitelist(
    secret_id: str,
    key: str | None = None,
    region: str | None = None,
) -> list[str]:
    """Read an IP whitelist from a Secrets Manager secret.

    Supports two secret formats:

    - **JSON array** (preferred): ``["203.0.113.10/32", "10.0.0.0/8"]``
    - **JSON object** with key: ``{"emp_ip_whitelist": ["203.0.113.10/32"]}``
      (use the *key* parameter to specify the key name)

    Args:
        secret_id: The secret name (e.g., ``aap-prod/iac/ip-whitelist``).
        key: Optional JSON key. If ``None``, expects the secret to
            be a raw JSON array.
        region: Optional region override.

    Returns:
        List of CIDR strings (e.g., ``["203.0.113.10/32"]``).
    """
    raw = get_secret_value(secret_id, region=region)
    data = json.loads(raw)

    if key is None:
        # Expect a raw JSON array
        if isinstance(data, list):
            return data
        raise FoundryError(
            f"Secret '{secret_id}' is not a JSON array (got {type(data).__name__}).\n"
            f"  Expected format: [\"1.2.3.4/32\", ...]"
        )

    # Expect a JSON object with the specified key
    if not isinstance(data, dict):
        raise FoundryError(
            f"Secret '{secret_id}' is not a JSON object (got {type(data).__name__})"
        )
    whitelist = data.get(key)
    if whitelist is None:
        raise FoundryError(
            f"Secret '{secret_id}' has no key '{key}'.\n"
            f"  Available keys: {', '.join(data.keys())}"
        )
    if not isinstance(whitelist, list):
        raise FoundryError(
            f"Secret '{secret_id}' key '{key}' is not a list (got {type(whitelist).__name__})"
        )
    return whitelist


__all__ = [
    "AWSCallerIdentity",
    "AWSCredentialStatus",
    "detect_aws_credentials",
    "get_secret_json",
    "get_secret_value",
    "put_secret_value",
    "resolve_caller_identity",
    "resolve_hosted_zone_id",
    "resolve_ip_whitelist",
]
