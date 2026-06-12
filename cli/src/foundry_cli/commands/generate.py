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


@generate.command(name="static-iac")
@click.option(
    "--service", "service_name", required=True,
    help="Service key in the central manifest (strategy must be `static`).",
)
@click.option(
    "--manifest", "manifest_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Central platform manifest (default: <dir>/platform.json, else foundry.json).",
)
@click.option(
    "--out", "out_dir",
    type=click.Path(file_okay=False),
    default=".",
    help="Service repo checkout root. Files land under <out>/<deploy.iac.stackPath>/.",
)
@click.option("--env", "env_name", default="prod",
              help="Environment whose branch the OIDC trust is scoped to (default: prod).")
@click.pass_context
def static_iac(
    ctx: click.Context,
    service_name: str,
    manifest_path: str | None,
    out_dir: str,
    env_name: str,
) -> None:
    """Generate a static-site OpenTofu stack (S3 + CloudFront + ACM + Route53 + OIDC role).

    One generator instead of hand-copied per-repo stacks. Reads the service's
    deploy.iac (domain, hostedZoneId, bucket, wwwDomain, spaFallback, stateKey)
    plus the platform ci.state block; writes the stack into the service repo at
    deploy.iac.stackPath. Re-run to regenerate — manual edits are overwritten.
    """
    from foundry_cli.core.project.manifest import load_manifest_from_path
    from foundry_cli.generators.static_iac import generate_static_iac

    root = ctx.obj["directory"]
    mp = Path(manifest_path) if manifest_path else root / "platform.json"
    if not mp.exists():
        mp = root / "foundry.json"
    if not mp.exists():
        raise FoundryError(
            f"No central manifest found (looked for platform.json / foundry.json in {root})."
        )

    manifest = load_manifest_from_path(mp)
    try:
        spec, files = generate_static_iac(manifest, service_name, env_name)
    except ValueError as e:
        raise FoundryError(str(e)) from e

    # stackPath must stay inside the checkout (it comes from the manifest, but
    # the generator writes wherever it says — refuse absolute/.. escapes).
    sp = Path(spec.stack_path)
    if sp.is_absolute() or ".." in sp.parts:
        raise FoundryError(f"deploy.iac.stackPath must be repo-relative: {spec.stack_path}")
    stack_dir = Path(out_dir) / sp
    stack_dir.mkdir(parents=True, exist_ok=True)
    click.echo(click.style(
        f"🏗️  Generating static-site IaC for '{service_name}' ({spec.domain})...",
        fg="cyan", bold=True,
    ))
    for filename, content in sorted(files.items()):
        target = stack_dir / filename
        target.write_text(content, encoding="utf-8", newline="\n")
        click.echo(click.style("  ✅ ", fg="green") + click.style(str(target), fg="white"))
    click.echo(click.style(
        f"\n🎉 {len(files)} files in {stack_dir}. Bootstrap: run the first "
        "`tofu init && tofu apply` locally (creates the OIDC role CI assumes).",
        fg="green",
    ))


@generate.command(name="callers")
@click.option(
    "--manifest", "manifest_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Central platform manifest (default: <dir>/platform.json, else foundry.json).",
)
@click.option(
    "--out", "out_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Write under <out>/<repo>/.github/workflows/. Default: print to stdout.",
)
@click.option("--env", "env_name", default="prod", help="Target environment (default: prod).")
@click.option("--ref", default="main", help="foundry-ops ref the callers pin (default: main).")
@click.option(
    "--exclude-repo", "exclude_repos", multiple=True,
    help="owner/repo to skip (repeatable). Use for PUBLIC repos — they can't call "
         "the ops repo's private reusable workflow, so they self-deploy.",
)
@click.pass_context
def callers(
    ctx: click.Context,
    manifest_path: str | None,
    out_dir: str | None,
    env_name: str,
    ref: str,
    exclude_repos: tuple[str, ...],
) -> None:
    """Generate per-service thin-caller workflows from the central manifest.

    Multi-repo (v0.7.0): foundry-ops owns the pipeline; each service repo carries
    only a thin caller that names its service and delegates to the reusable
    deploy.yml. This emits those callers from platform.json.

    Exclude public-repo services with ``--exclude-repo owner/repo``: a thin caller
    delegates to the ops repo's private reusable workflow, and a public repo can't
    call a reusable workflow in a private repo.
    """
    from foundry_cli.core.project.manifest import load_manifest_from_path
    from foundry_cli.generators.callers import generate_all_callers

    root = ctx.obj["directory"]
    if manifest_path:
        mp = Path(manifest_path)
    else:
        mp = root / "platform.json"
        if not mp.exists():
            mp = root / "foundry.json"
    if not mp.exists():
        raise FoundryError(
            f"No central manifest found (looked for platform.json / foundry.json in {root})."
        )

    manifest = load_manifest_from_path(mp)
    results = generate_all_callers(
        manifest, env=env_name, ref=ref, exclude_repos=set(exclude_repos),
    )
    if not results:
        click.echo(
            click.style(
                "⚠️  No deployable services in the manifest — nothing to generate.",
                fg="yellow",
            )
        )
        return

    click.echo(click.style("🧩 Generating thin-caller workflows...", fg="cyan", bold=True))
    for (repo, filename), content in sorted(results.items()):
        if out_dir:
            target = Path(out_dir) / repo / ".github" / "workflows" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            click.echo(click.style("  ✅ ", fg="green") + click.style(str(target), fg="white"))
        else:
            click.echo(click.style(f"\n# ── {repo}/.github/workflows/{filename} ──", fg="cyan"))
            click.echo(content)
