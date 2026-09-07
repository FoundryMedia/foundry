from __future__ import annotations

import sys
import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project.workspace import (
    DiscoveredService,
    ServiceKind,
    filter_services,
    find_workspace_file,
    load_multi_workspace,
    load_workspace,
    load_workspace_file,
    select_services_by_names,
    service_repo_root,
)
from foundry_cli.core.project.service_runtime import RuntimeMatch, ServiceRuntime
from foundry_cli.core.project.manifest import ServiceConfig
from foundry_cli.core.ui.runner import ServicesUI
from foundry_cli.core.services.factory import create_runner, create_sidecar_runner
from foundry_cli.core.logging import (
    suppress_async_cleanup_warnings,
    write_crash_log,
)


class RunGroup(FoundryGroup):
    """FoundryGroup with profile shorthand: ``dev:core`` → ``dev --profile core``."""

    def resolve_command(self, ctx: click.Context, args):
        if args and ":" in args[0] and not args[0].startswith("-"):
            base, _, profile = args[0].partition(":")
            if profile and base in self.commands:
                args = [base, "--profile", profile, *args[1:]]
        return super().resolve_command(ctx, args)


@click.group(cls=RunGroup, invoke_without_command=False)
@click.option("-d", "--debug", is_flag=True, default=False, help="Show debug output (must appear before the subcommand; aliases will hoist it).")
@click.pass_context
def run(ctx: click.Context, debug: bool) -> None:
    """Start Foundry services locally."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    return


run.help_tip = "VSCode users, in Settings set terminal.integrated.stickyScroll.enabled to false"


_EMERGENCY_HANDLERS_INSTALLED = False


def _install_emergency_teardown() -> None:
    """Reap child service processes when foundry itself dies.

    SIGTERM/SIGHUP and normal interpreter exit sweep every registered child
    process tree (mvn -> java survive nothing here). SIGKILL of foundry is
    the one unfixable case — nothing runs then.
    """
    global _EMERGENCY_HANDLERS_INSTALLED
    if _EMERGENCY_HANDLERS_INSTALLED:
        return
    _EMERGENCY_HANDLERS_INSTALLED = True

    import atexit
    import os
    import signal

    from foundry_cli.core.services.runners.process import kill_all_live_children

    atexit.register(kill_all_live_children)

    def _emergency(signum, frame):  # noqa: ANN001
        kill_all_live_children()
        try:
            signal.signal(signum, signal.SIG_DFL)
        except (ValueError, OSError):
            pass
        os.kill(os.getpid(), signum)

    handled = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        handled.append(signal.SIGHUP)
    for sig in handled:
        try:
            signal.signal(sig, _emergency)
        except (ValueError, OSError):
            pass


def _run_services_ui(
    command: str,
    *,
    filter_svc: str | None = None,
    migrate_db: bool = False,
    profile: str | None = None,
    no_tui: bool = False,
) -> None:
    """Common logic for running services with the UI."""
    import click
    ctx = click.get_current_context()
    debug = bool((ctx.obj or {}).get("debug"))

    notices: list[str] = []
    multi = False
    if profile:
        # Profile run: always the cross-repo workspace view.
        ws_path = find_workspace_file()
        if ws_path is None:
            raise FoundryError(
                f"Profile '{profile}' requires a foundry.workspace.json "
                "(searched the current directory, its parents, and their immediate "
                "children; set FOUNDRY_WORKSPACE to point at one)."
            )
        ws_file = load_workspace_file(ws_path)
        if profile not in ws_file.profiles:
            available = ", ".join(sorted(ws_file.profiles)) or "(none defined)"
            raise FoundryError(
                f"Unknown profile '{profile}' in {ws_path}. Available: {available}"
            )
        multi = True
        workspace, services_root, services, sidecars, notices = load_multi_workspace(
            ws_file, command=command
        )
        services, sidecars, missing = select_services_by_names(
            services, sidecars, ws_file.profiles[profile]
        )
        for name in missing:
            notices.append(
                f"profile '{profile}' names unknown service '{name}' (repo not cloned?)"
            )
    else:
        try:
            workspace, services_root, services, sidecars = load_workspace(command=command)
            notices.extend(workspace.notices)
        except FoundryError:
            # Not inside a repo with a manifest — fall back to the cross-repo
            # workspace (everything discoverable), if one is findable.
            ws_path = find_workspace_file()
            if ws_path is None:
                raise
            ws_file = load_workspace_file(ws_path)
            multi = True
            workspace, services_root, services, sidecars, notices = load_multi_workspace(
                ws_file, command=command
            )

    for note in notices:
        click.echo(click.style(f"Note: {note}", fg="yellow"))

    # Apply service filter if specified
    if filter_svc:
        filter_names = [s.strip() for s in filter_svc.split(",") if s.strip()]
        if filter_names:
            known = {s.name for s in services}
            unknown = [n for n in filter_names if n not in known]
            if unknown:
                click.echo(click.style(
                    f"Warning: unknown service(s) in --filter: {', '.join(unknown)}",
                    fg="yellow",
                ))
                click.echo(f"  Available: {', '.join(sorted(known))}")
            if multi:
                # Cross-repo: plain name selection (no Node dependency
                # expansion across repo boundaries).
                services, sidecars, _ = select_services_by_names(
                    services, sidecars, filter_names
                )
            else:
                services, sidecars = filter_services(services, sidecars, filter_names, workspace.root)

    if debug:
        project_name = workspace.manifests[0].name or "Unnamed Project"
        print(f"Project: {project_name}")
        print(f"Services root: {services_root}")
        print(f"Command: {command}")

    # Build list of services with their sidecars inserted right after them
    # Sidecars should appear as sub-items under their parent service
    all_services = []
    
    for svc in services:
        all_services.append(svc)
        
        # Add sidecars for this service right after it
        service_sidecars = [s for s in sidecars if s.parent_service == svc.name]
        for sidecar in service_sidecars:
            # Use a clean ID-safe name: parent/sidecar format
            sidecar_id = f"{svc.name}/{sidecar.name}"
            pseudo_service = DiscoveredService(
                name=sidecar_id,  # Clean ID for internal use
                path=workspace.root,
                runtime=RuntimeMatch(ServiceRuntime.unknown, f"sidecar: {sidecar.config.command}"),
                kind=ServiceKind.sidecar,
                config=ServiceConfig(),
            )
            all_services.append(pseudo_service)

    if not all_services:
        if debug:
            print("No services found.")
        return

    if debug:
        print("Discovered services:")
        for svc in services:
            print(f"  - {svc.name} ({svc.kind}) [{svc.runtime.runtime}] ({svc.runtime.evidence})")
            print(f"    {svc.path}")
            service_sidecars = [s for s in sidecars if s.parent_service == svc.name]
            for sidecar in service_sidecars:
                print(f"      +-- {sidecar.name} (sidecar: {sidecar.config.command})")

    # Create runners: sidecars use create_sidecar_runner, services use create_runner.
    # Roots resolve PER SERVICE (each repo owns its own pem paths / env files) —
    # in single-repo mode the walk-up lands on workspace.root anyway.
    svc_by_name = {s.name: s for s in services}

    def _root_for(svc: DiscoveredService | None):
        if svc is None:
            return workspace.root
        return service_repo_root(svc.path) or workspace.root

    runners = {}
    for sidecar in sidecars:
        # Use parent/sidecar format as the key to match all_services
        sidecar_id = f"{sidecar.parent_service}/{sidecar.name}"
        # Display name shows tree hierarchy: └─ name#sidecar
        display_name = f"└─ {sidecar.name}#sidecar"
        runners[sidecar_id] = create_sidecar_runner(
            sidecar, _root_for(svc_by_name.get(sidecar.parent_service)),
            debug=debug, sidecar_id=sidecar_id, display_name=display_name,
        )
    for svc in services:
        runners[svc.name] = create_runner(
            svc, debug=debug, command=command, migrate_db=migrate_db,
            workspace_root=_root_for(svc),
        )

    _install_emergency_teardown()

    # Suppress the asyncio cleanup warnings that happen on Windows
    suppress_async_cleanup_warnings()

    from foundry_cli.core.ui.headless import (
        HeadlessServicesRunner,
        headless_mode_requested,
    )

    if headless_mode_requested(no_tui):
        exit_code = HeadlessServicesRunner(all_services, runners, debug=debug).run()
        if exit_code:
            raise SystemExit(exit_code)
        return

    app = ServicesUI(all_services, runners, debug=debug)

    try:
        app.run()
    except KeyboardInterrupt:
        # User spammed Ctrl+C during shutdown - suppress the traceback
        pass
    except Exception as e:
        # Unexpected error - log it and show a friendly message
        log_path = write_crash_log(type(e), e, e.__traceback__, context="ServicesUI.run()")
        print(click.style(f"\nAn unexpected error occurred: {e}", fg="red", bold=True))
        print(click.style(f"Details written to: {log_path}", fg="yellow"))
        return

    # Fatal startup failure (every service failed, none ever healthy): the
    # TUI exits itself with return_code 1 — print the full errors plainly
    # (no panel truncation) and propagate a nonzero status for scripts/CI.
    if getattr(app, "return_code", 0):
        print(click.style("\nRun failed — every service failed to start:", fg="red", bold=True))
        for svc_name, error in getattr(app, "fatal_failures", {}).items():
            print(click.style(f"  {svc_name}: ", fg="red", bold=True) + error)
        raise SystemExit(app.return_code or 1)

    print(click.style("Shutdown gracefully. Goodbye!", fg="green", bold=True))


@run.command(add_help_option=False)
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of services to run (dependencies are included automatically).")
@click.option("--migrate-db", "-mdb", is_flag=True, default=False, help="Run Liquibase database migrations before starting services that have a database block.")
@click.option("--profile", "profile", default=None, help="Named workspace profile from foundry.workspace.json (shorthand: `foundry run dev:<profile>`).")
@click.option("--env", "dev_environment", default=None, help="Named environment overlay: applies each service's environments.<name> run/env/sshTunnels blocks and layers .foundry/dev.<name>[.local].env. Equivalent to FOUNDRY_DEV_ENV (the flag wins). Distinct ports per env let two environments run side by side.")
@click.option("--no-tui", "no_tui", is_flag=True, default=False, help="Plain-text streaming output instead of the full-screen UI (auto-selected when stdout is not a TTY or FOUNDRY_NO_TUI is set). Exits nonzero when every service fails.")
@click.pass_context
def dev(ctx: click.Context, filter_svc: str | None, migrate_db: bool, profile: str | None, dev_environment: str | None, no_tui: bool) -> None:
    """Run the platform in development mode with the Services UI."""
    if dev_environment:
        import os

        os.environ["FOUNDRY_DEV_ENV"] = dev_environment.strip()
    _run_services_ui("dev", filter_svc=filter_svc, migrate_db=migrate_db, profile=profile, no_tui=no_tui)


@run.command(add_help_option=False)
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of services to run (dependencies are included automatically).")
@click.option("--profile", "profile", default=None, help="Named workspace profile from foundry.workspace.json (shorthand: `foundry run build:<profile>`).")
@click.option("--no-tui", "no_tui", is_flag=True, default=False, help="Plain-text streaming output instead of the full-screen UI (auto-selected when stdout is not a TTY or FOUNDRY_NO_TUI is set).")
@click.pass_context
def build(ctx: click.Context, filter_svc: str | None, profile: str | None, no_tui: bool) -> None:
    """Run the build command for all services."""
    _run_services_ui("build", filter_svc=filter_svc, profile=profile, no_tui=no_tui)
    
    