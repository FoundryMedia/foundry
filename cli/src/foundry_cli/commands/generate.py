"""``foundry generate`` — Generate pipeline, deployment scripts, and IaC variable files.

Reads ``foundry.json``, resolves deployment profiles via the convention
engine, and emits:

- **pipeline** — CI/CD pipeline YAML (GitHub Actions)
- **scripts** — Self-contained deployment scripts in ``ci/scripts/``
- **tfvars** — OpenTofu variable files in ``ci/iac/{env}/``

Use ``--clean`` to wipe the target directory before generating.
"""
from __future__ import annotations

import json
from pathlib import Path

import click

from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project.manifest import ProjectManifest


def _load_manifest(directory: Path) -> ProjectManifest:
    """Load ``foundry.json`` from the given directory."""
    manifest_path = directory / "foundry.json"
    if not manifest_path.exists():
        raise FoundryError(
            f"No foundry.json found in {directory}.\n"
            "Run 'foundry init' to create one, or pass --dir."
        )
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return ProjectManifest(path=manifest_path, data=data)


@click.group(invoke_without_command=True)
@click.option(
    "-d", "--dir",
    "directory",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    default=".",
    help="Project root containing foundry.json (default: cwd).",
)
@click.option(
    "--clean",
    is_flag=True,
    default=False,
    help="Wipe target directories before generating (fresh install).",
)
@click.pass_context
def generate(ctx: click.Context, directory: str, clean: bool) -> None:
    """Generate pipeline and deployment scripts from foundry.json."""
    ctx.ensure_object(dict)
    ctx.obj["directory"] = Path(directory)
    ctx.obj["clean"] = clean

    # If invoked without a subcommand, run everything
    if ctx.invoked_subcommand is None:
        ctx.invoke(pipeline)
        ctx.invoke(scripts)
        ctx.invoke(tfvars)


@generate.command()
@click.option("--clean", is_flag=True, default=False, hidden=True, help="Inherited from parent.")
@click.pass_context
def pipeline(ctx: click.Context, clean: bool) -> None:
    """Generate CI/CD pipeline YAML (GitHub Actions)."""
    from foundry_cli.generators.pipeline import write_pipeline

    root = ctx.obj["directory"]
    clean = clean or ctx.obj["clean"]

    manifest = _load_manifest(root)

    ci_dir = manifest.data.get("ci", {}).get("iacDir", "ci/iac")
    # Pipeline goes next to foundry.json: .github/workflows/deploy.yml
    pipeline_dir = root / ".github" / "workflows"

    click.echo(click.style("📋 Generating pipeline...", fg="cyan", bold=True))
    output_path = write_pipeline(manifest, pipeline_dir / "deploy.yml", clean=clean)
    click.echo(
        click.style("  ✅ ", fg="green")
        + click.style(str(output_path.relative_to(root)), fg="white")
    )


@generate.command()
@click.option("--clean", is_flag=True, default=False, hidden=True, help="Inherited from parent.")
@click.pass_context
def scripts(ctx: click.Context, clean: bool) -> None:
    """Generate deployment scripts in ci/scripts/."""
    from foundry_cli.generators.scripts import generate_scripts

    root = ctx.obj["directory"]
    clean = clean or ctx.obj["clean"]

    manifest = _load_manifest(root)

    ci_dir_name = manifest.data.get("structure", {}).get("ciDir", "ci")
    scripts_dir = root / ci_dir_name / "scripts"

    click.echo(click.style("📜 Generating deployment scripts...", fg="cyan", bold=True))
    generated = generate_scripts(manifest, scripts_dir, clean=clean)

    for path in generated:
        rel = path.relative_to(root)
        click.echo(
            click.style("  ✅ ", fg="green")
            + click.style(str(rel), fg="white")
        )

    click.echo(
        click.style(f"\n🎉 Generated {len(generated)} files in ", fg="green", bold=True)
        + click.style(str(scripts_dir.relative_to(root)), fg="cyan", bold=True)
    )


@generate.command()
@click.option("--clean", is_flag=True, default=False, hidden=True, help="Inherited from parent.")
@click.pass_context
def tfvars(ctx: click.Context, clean: bool) -> None:
    """Generate OpenTofu variable files in ci/iac/{env}/."""
    from foundry_cli.generators.tfvars import write_tfvars

    root = ctx.obj["directory"]
    clean = clean or ctx.obj["clean"]

    manifest = _load_manifest(root)

    ci = manifest.data.get("ci", {})
    iac_dir_name = ci.get("iacDir", "ci/iac")
    iac_dir = root / iac_dir_name

    environments = manifest.environments
    enabled_envs = {
        name: cfg for name, cfg in environments.items() if cfg.enabled
    }

    if not enabled_envs:
        click.echo(click.style("⚠️  No enabled environments — nothing to generate.", fg="yellow"))
        return

    click.echo(click.style("🏗️  Generating tfvars...", fg="cyan", bold=True))

    generated_count = 0
    for env_name in sorted(enabled_envs):
        env_dir = iac_dir / env_name
        output_path = env_dir / f"{env_name}.auto.tfvars"

        out = write_tfvars(manifest, env_name, output_path)
        rel = out.relative_to(root)
        click.echo(
            click.style("  ✅ ", fg="green")
            + click.style(str(rel), fg="white")
        )
        generated_count += 1

    if generated_count:
        click.echo(
            click.style(f"\n🎉 Generated {generated_count} tfvars file(s)", fg="green", bold=True)
        )
        click.echo(
            click.style(
                "\n⚠️  Service renames require state migration before applying!\n"
                "   Run: tofu state mv 'module.ecs_services[\"old_name\"]' "
                "'module.ecs_services[\"new_name\"]'",
                fg="yellow",
            )
        )
