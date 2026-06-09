"""Code generators for Foundry-managed platforms.

The ``generators`` package contains the convention engine, deployment profile
resolution, and code/pipeline generators that power ``foundry generate``.

Modules:

- ``conventions`` — Pure-function convention engine (DeploymentProfile resolution)
- ``pipeline`` — GitHub Actions workflow YAML generator
- ``scripts`` — Self-contained deployment scripts generator (ci/scripts/)
- ``tfvars`` — OpenTofu variable file generator (ci/iac/{env}/)
"""

from foundry_cli.generators.conventions import (
    DeploymentProfile,
    resolve_all_profiles,
    resolve_deployment_profile,
)
from foundry_cli.generators.pipeline import generate_pipeline_yaml, write_pipeline
from foundry_cli.generators.scripts import generate_scripts
from foundry_cli.generators.tfvars import (
    generate_tfvars,
    iac_service_name,
    iac_static_site_name,
    write_tfvars,
)

__all__ = [
    "DeploymentProfile",
    "resolve_all_profiles",
    "resolve_deployment_profile",
    "generate_pipeline_yaml",
    "write_pipeline",
    "generate_scripts",
    "generate_tfvars",
    "iac_service_name",
    "iac_static_site_name",
    "write_tfvars",
]
