"""Command Line Interface for SkillManager."""

import json
import sys
from pathlib import Path
from typing import List, Optional
import typer
from rich.console import Console
from rich.table import Table

from skill_manager.config import AppConfig, load_config
from skill_manager.core.indexer import (
    IndexSchemaError,
    audit_skill,
    complete_skill,
)
from skill_manager.core.remote_search import (
    RateLimitExceededError,
    RemoteSearchError,
    search_remote_skills,
)
from skill_manager.core.scanner import scan_skills
from skill_manager.core.versioning import (
    DirtyWorktreeError,
    GitVersionError,
    check_version_status,
    rollback_skill,
    upgrade_skill,
)
from skill_manager.core.workflow_auditor import (
    audit_workflow_skills,
    complete_workflow_skills,
)
from skill_manager.core.mode_controller import (
    toggle_skill_mode,
    apply_global_policy,
)
from skill_manager.models import (
    GlobalPolicyMode,
    PlatformType,
    SkillExecutionMode,
    VersionStatus,
    WorkflowSkillStatus,
)

app = typer.Typer(
    name="skill-manager",
    help="Cross-platform Local AI Skills & Plugins Manager",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    no_tui: bool = typer.Option(False, "--no-tui", help="Disable TUI on root invocation"),
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
):
    """Cross-platform Local AI Skills & Plugins Manager root entrypoint."""
    if version:
        from skill_manager import __version__
        console.print(f"skill-manager v{__version__}")
        raise typer.Exit(code=0)

    if ctx.invoked_subcommand is None:
        # User executed `skill-manager` directly without subcommands
        if not no_tui and sys.stdin.isatty():
            try:
                from skill_manager.tui.app import SkillManagerApp
                tui_app = SkillManagerApp()
                tui_app.run()
                raise typer.Exit(code=0)
            except Exception as e:
                err_console.print(f"[yellow]TUI initialization skipped: {e}[/yellow]")

        # Safe fallback to help in non-interactive / pipeline / --no-tui mode (EC-11)
        console.print(ctx.get_help())
        raise typer.Exit(code=0)


def _output(data: dict, format_type: str, render_table_fn):
    """Output data as clean JSON or Rich table."""
    if format_type.lower() == "json":
        # Output clean JSON without ANSI color codes
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    else:
        render_table_fn()


@app.command()
def scan(
    platform: str = typer.Option("all", "--platform", "-p", help="Target platform (claude, antigravity, codex, cursor, universal, all)"),
    paths: Optional[List[str]] = typer.Option(None, "--path", "--custom-paths", "--custom_paths", help="Custom paths to scan"),
    depth: int = typer.Option(3, "--depth", "-d", min=1, max=5, help="Scan depth (1-5)"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Scan local storage for installed skills and plugins across platforms."""
    try:
        plat_enum = PlatformType(platform.lower())
    except ValueError:
        err_console.print(f"[bold red]VALIDATION_ERROR:[/bold red] Invalid platform '{platform}'.")
        raise typer.Exit(code=2)

    cfg = load_config(config)
    result = scan_skills(platform=plat_enum, custom_paths=paths, max_depth=depth, config=cfg)

    def render():
        table = Table(title="Local Installed Skills")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold green")
        table.add_column("Platform", style="magenta")
        table.add_column("SKILL.md", style="yellow")
        table.add_column("Version", style="blue")
        table.add_column("Path", style="dim")

        for s in result.skills:
            table.add_row(
                s.id,
                s.name,
                s.platform.value,
                "✓" if s.has_skill_md else "✗",
                s.version_status.value,
                s.path,
            )
        console.print(table)
        console.print(f"Total skills found: {result.summary.valid_skills}")

    _output(result.model_dump(), format, render)
    raise typer.Exit(code=0)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search keyword (2-100 characters)"),
    source: str = typer.Option("all", "--source", "-s", help="Source: github, huggingface, or all"),
    sort: str = typer.Option("stars", "--sort", help="Sort by: stars or updated"),
    limit: int = typer.Option(20, "--limit", "-l", help="Number of results to retrieve (1-50)"),
    page: int = typer.Option(1, "--page", help="Page number"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
):
    """Search for agent skills on GitHub and HuggingFace Hub."""
    try:
        res = search_remote_skills(
            query=query,
            source=source,
            sort_by=sort,
            limit=limit,
            page=page,
        )
    except ValueError as ve:
        err_console.print(f"[bold red]{ve}[/bold red]")
        raise typer.Exit(code=2)
    except RateLimitExceededError as rle:
        err_console.print(f"[bold red]{rle}[/bold red]")
        raise typer.Exit(code=4)
    except RemoteSearchError as rse:
        err_console.print(f"[bold red]{rse}[/bold red]")
        raise typer.Exit(code=4)

    def render():
        table = Table(title=f"Remote Skills Search Results for '{query}'")
        table.add_column("Source", style="cyan")
        table.add_column("Repository / ID", style="bold green")
        table.add_column("Stars/Likes", style="yellow")
        table.add_column("Description", style="white")

        for item in res.items:
            table.add_row(
                item.source,
                item.repo_id,
                str(item.stars_or_downloads),
                (item.description or "")[:60],
            )
        console.print(table)
        console.print(f"Showing {len(res.items)} of {res.total_count} results")

    _output(res.model_dump(), format, render)
    raise typer.Exit(code=0)


@app.command()
def audit(
    target: str = typer.Option(..., "--target", "-t", help="Target skill directory path"),
    index: Optional[str] = typer.Option(None, "--index", "-i", help="index.md specification path"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
):
    """Audit a local skill structure against index.md specifications."""
    target_path = Path(target).resolve()
    index_path = Path(index).resolve() if index else None

    try:
        res = audit_skill(target_path, index_path=index_path)
    except FileNotFoundError as fnf:
        err_console.print(f"[bold red]ERR_PATH_NOT_FOUND:[/bold red] {fnf}")
        raise typer.Exit(code=2)
    except ValueError as ve:
        err_console.print(f"[bold red]{ve}[/bold red]")
        raise typer.Exit(code=2)
    except IndexSchemaError as ise:
        err_console.print(f"[bold red]{ise}[/bold red]")
        raise typer.Exit(code=3)
    except PermissionError as pe:
        err_console.print(f"[bold red]ACCESS_DENIED:[/bold red] {pe}")
        raise typer.Exit(code=5)

    def render():
        status_str = "[bold green]COMPLIANT[/bold green]" if res.is_compliant else "[bold red]NON-COMPLIANT[/bold red]"
        console.print(f"Audit Status: {status_str}")
        if not res.is_compliant:
            if res.missing_fields:
                console.print(f"[yellow]Missing Frontmatter Fields:[/yellow] {', '.join(res.missing_fields)}")
            if res.missing_sections:
                console.print(f"[yellow]Missing Sections:[/yellow] {', '.join(res.missing_sections)}")
            if res.missing_dirs:
                console.print(f"[yellow]Missing Subdirectories:[/yellow] {', '.join(res.missing_dirs)}")
            if res.diff_content:
                console.print("\n[bold]Suggested Unified Diff:[/bold]")
                console.print(res.diff_content)

    _output(res.model_dump(), format, render)
    raise typer.Exit(code=0)


@app.command()
def complete(
    target: str = typer.Option(..., "--target", "-t", help="Target skill directory path"),
    index: Optional[str] = typer.Option(None, "--index", "-i", help="index.md specification path"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Whether to simulate changes without disk write"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
):
    """Auto-complete missing SKILL.md sections and subdirectories based on index.md."""
    target_path = Path(target).resolve()
    index_path = Path(index).resolve() if index else None

    try:
        success, diff_text, modified = complete_skill(target_path, index_path=index_path, dry_run=dry_run)
    except FileNotFoundError as fnf:
        err_console.print(f"[bold red]ERR_PATH_NOT_FOUND:[/bold red] {fnf}")
        raise typer.Exit(code=2)
    except IndexSchemaError as ise:
        err_console.print(f"[bold red]{ise}[/bold red]")
        raise typer.Exit(code=3)
    except PermissionError as pe:
        err_console.print(f"[bold red]ACCESS_DENIED:[/bold red] {pe}")
        raise typer.Exit(code=5)
    except PermissionError as pe:
        err_console.print(f"[bold red]{pe}[/bold red]")
        raise typer.Exit(code=5)

    data = {
        "success": success,
        "dry_run": dry_run,
        "modified_files": modified,
        "diff": diff_text,
    }

    def render():
        action = "[yellow](DRY RUN)[/yellow]" if dry_run else "[green](APPLIED)[/green]"
        console.print(f"Skill Completion {action}:")
        if modified:
            console.print(f"Files affected: {', '.join(modified)}")
            if diff_text:
                console.print("\n[bold]Diff Content:[/bold]")
                console.print(diff_text)
        else:
            console.print("[green]Skill is already complete and fully compliant![/green]")

    _output(data, format, render)
    raise typer.Exit(code=0)


@app.command()
def track(
    action: str = typer.Argument(..., help="Action: status, upgrade, or rollback"),
    target: str = typer.Option(..., "--target", "-t", help="Target skill directory path"),
    ref: Optional[str] = typer.Option(None, "--ref", help="Target git ref or commit SHA"),
    force: bool = typer.Option(False, "--force", help="Force upgrade even if uncommitted changes exist"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
):
    """Track, upgrade, or roll back skill versions."""
    target_path = Path(target).resolve()

    try:
        if action == "status":
            res = check_version_status(target_path)
        elif action == "upgrade":
            res = upgrade_skill(target_path, target_ref=ref, force=force)
        elif action == "rollback":
            res = rollback_skill(target_path, tag_name=ref)
        else:
            err_console.print(f"[bold red]INVALID_ACTION:[/bold red] Unknown action '{action}'.")
            raise typer.Exit(code=2)
    except DirtyWorktreeError as dwe:
        err_console.print(f"[bold red]{dwe}[/bold red]")
        raise typer.Exit(code=6)
    except GitVersionError as gve:
        err_console.print(f"[bold red]{gve}[/bold red]")
        raise typer.Exit(code=7)

    def render():
        table = Table(title=f"Version Track for '{res.skill_name}'")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="bold")
        table.add_row("Status", res.version_status.value)
        table.add_row("Local Commit", (res.local_commit or "N/A")[:10])
        table.add_row("Remote Commit", (res.remote_commit or "N/A")[:10])
        table.add_row("Commits Behind", str(res.behind_count))
        if res.diff_summary:
            table.add_row("Summary", res.diff_summary)
        console.print(table)

    _output(res.model_dump(), format, render)
    if res.version_status == VersionStatus.NETWORK_TIMEOUT:
        raise typer.Exit(code=7)
    raise typer.Exit(code=0)


@app.command()
def config(
    action: str = typer.Argument("show", help="Action: show"),
    config_file: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
):
    """Manage and inspect SkillManager configuration (FR-05)."""
    cfg = load_config(config_file)
    data = {
        "custom_platform_paths": {k: [str(p) for p in v] for k, v in cfg.custom_platform_paths.items()},
        "github_token_configured": bool(cfg.github_token),
        "hf_token_configured": bool(cfg.hf_token),
    }

    def render():
        table = Table(title="SkillManager Configuration")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="bold")
        table.add_row("GitHub Token", "Configured" if cfg.github_token else "Not Set")
        table.add_row("HuggingFace Token", "Configured" if cfg.hf_token else "Not Set")
        for plat, p_list in cfg.custom_platform_paths.items():
            table.add_row(f"Custom Path ({plat})", ", ".join(str(p) for p in p_list))
        console.print(table)

    _output(data, format, render)
    raise typer.Exit(code=0)


@app.command(name="workflow-audit")
def workflow_audit_cmd(
    workflow: Optional[str] = typer.Option(None, "--workflow", "-w", help="Workflow specification file path (default: auto-detected workflow.md)"),
    platform: str = typer.Option("all", "--platform", "-p", help="Target platform (claude, antigravity, codex, cursor, universal, all)"),
    target_dir: Optional[str] = typer.Option(None, "--target-dir", "-t", help="Directory where missing skills will be installed/created"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Candidate directories to copy existing skills from"),
    auto_complete: bool = typer.Option(False, "--auto-complete", "-a", help="Automatically complete missing or incomplete skills"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Whether to simulate changes without disk write"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
):
    """Audit installed skills against current workflow requirements and optionally auto-complete."""
    try:
        plat_enum = PlatformType(platform.lower())
    except ValueError:
        err_console.print(f"[bold red]VALIDATION_ERROR:[/bold red] Invalid platform '{platform}'.")
        raise typer.Exit(code=2)

    cfg = load_config(config)
    wf_path = Path(workflow).resolve() if workflow else None
    t_dir = Path(target_dir).resolve() if target_dir else None
    src_dirs = [Path(s).resolve() for s in sources] if sources else None
    c_paths = [str(t_dir)] if t_dir else None

    try:
        audit_res = audit_workflow_skills(
            workflow_path=wf_path,
            platform=plat_enum,
            custom_paths=c_paths,
            config=cfg,
        )
    except FileNotFoundError as fnf:
        err_console.print(f"[bold red]ERR_WORKFLOW_NOT_FOUND:[/bold red] {fnf}")
        raise typer.Exit(code=2)
    except ValueError as ve:
        err_console.print(f"[bold red]{ve}[/bold red]")
        raise typer.Exit(code=2)

    # Perform auto-completion if requested
    if auto_complete:
        try:
            comp_res = complete_workflow_skills(
                audit_result=audit_res,
                target_dir=t_dir,
                skill_sources=src_dirs,
                dry_run=dry_run,
            )
            audit_res.completion_result = comp_res
        except PermissionError as pe:
            err_console.print(f"[bold red]{pe}[/bold red]")
            raise typer.Exit(code=5)

    def render():
        table = Table(title=f"Workflow Skills Audit: {Path(audit_res.workflow_path).name}")
        table.add_column("Skill Name", style="bold green")
        table.add_column("Status", style="bold")
        table.add_column("Details", style="dim")

        if audit_res.total_required == 0:
            console.print("[yellow]NO_SKILL_REQUIREMENTS_FOUND: No skill references detected in workflow file.[/yellow]")
            return

        for req in audit_res.skills:
            if req.status == WorkflowSkillStatus.INSTALLED:
                status_display = "[bold green]INSTALLED[/bold green]"
                detail = req.installed_path or ""
            elif req.status == WorkflowSkillStatus.INCOMPLETE:
                status_display = "[bold yellow]INCOMPLETE[/bold yellow]"
                missing = []
                if req.missing_sections:
                    missing.append(f"sections: {', '.join(req.missing_sections)}")
                if req.missing_dirs:
                    missing.append(f"dirs: {', '.join(req.missing_dirs)}")
                detail = f"Missing {'; '.join(missing)}"
            else:
                status_display = "[bold red]MISSING[/bold red]"
                detail = "Not found in local skills directories"

            table.add_row(req.name, status_display, detail)

        console.print(table)
        console.print(
            f"Summary: Total: {audit_res.total_required} | "
            f"Installed: [green]{audit_res.installed_count}[/green] | "
            f"Incomplete: [yellow]{audit_res.incomplete_count}[/yellow] | "
            f"Missing: [red]{audit_res.missing_count}[/red]"
        )

        if audit_res.completion_result:
            comp = audit_res.completion_result
            mode = "[yellow](DRY RUN)[/yellow]" if comp.dry_run else "[green](APPLIED)[/green]"
            console.print(f"\nAuto-Completion {mode}:")
            if comp.completed_skills:
                console.print(f"Completed skills: {', '.join(comp.completed_skills)}")
            if comp.created_skeletons:
                console.print(f"Generated skeletons: {', '.join(comp.created_skeletons)}")
            if comp.diff_summary:
                console.print("\n[bold]Diff Summary:[/bold]")
                console.print(comp.diff_summary)

    _output(audit_res.model_dump(), format, render)
    raise typer.Exit(code=0)


@app.command()
def healthcheck(
    format: str = typer.Option("json", "--format", "-f", help="Output format: table or json"),
):
    """Execute system health check probe for container and runtime readiness."""
    from skill_manager import __version__

    payload = {
        "status": "healthy",
        "code": 200,
        "version": __version__,
        "python": sys.version.split()[0],
    }

    def render():
        console.print(f"[bold green]HEALTHY (200)[/bold green] - skill-manager v{__version__} (Python {payload['python']})")

    _output(payload, format, render)
    raise typer.Exit(code=0)


@app.command()
def mode(
    skill: Optional[str] = typer.Argument(None, help="Target skill directory path or name"),
    set_mode: Optional[str] = typer.Option(None, "--set", "-s", help="Target mode: resident or on_demand"),
    policy: Optional[str] = typer.Option(None, "--policy", help="Global policy: all_resident, all_on_demand, restore_last"),
    platform: str = typer.Option("all", "--platform", "-p", help="Target platform (claude, antigravity, codex, cursor, universal, all)"),
    paths: Optional[List[str]] = typer.Option(None, "--path", "--custom-paths", help="Custom paths to scan"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
):
    """Inspect or toggle skill execution mode and apply global policy (FR-07, FR-08, FR-13)."""
    cfg = load_config(config)
    try:
        plat_enum = PlatformType(platform.lower())
    except ValueError:
        err_console.print(f"[bold red]VALIDATION_ERROR:[/bold red] Invalid platform '{platform}'.")
        raise typer.Exit(code=2)

    # 1. Handle global policy application
    if policy:
        try:
            pol_enum = GlobalPolicyMode(policy.lower())
        except ValueError:
            err_console.print(f"[bold red]VALIDATION_ERROR:[/bold red] Invalid policy '{policy}'. Choose: all_resident, all_on_demand, restore_last")
            raise typer.Exit(code=2)

        scan_res = scan_skills(platform=plat_enum, custom_paths=paths, config=cfg)
        ev = apply_global_policy(pol_enum, scan_res.skills, platform=plat_enum, config_path=config)

        payload = {
            "policy": ev.policy.value if hasattr(ev.policy, "value") else str(ev.policy),
            "affected_count": ev.affected_count,
            "success": ev.success,
            "error_message": ev.error_message,
        }

        def render():
            if ev.success:
                console.print(f"[bold green]Applied global policy '{ev.policy.value}' to {ev.affected_count} skills.[/bold green]")
            else:
                err_console.print(f"[bold red]Global policy failed:[/bold red] {ev.error_message}")

        _output(payload, format, render)
        if not ev.success:
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    # 2. Handle single skill mode toggling
    if skill and set_mode:
        try:
            target_mode = SkillExecutionMode(set_mode.lower())
        except ValueError:
            err_console.print(f"[bold red]VALIDATION_ERROR:[/bold red] Invalid mode '{set_mode}'. Choose: resident or on_demand")
            raise typer.Exit(code=2)

        skill_path = Path(skill)
        if not skill_path.exists():
            # Try to find skill by name among scanned skills
            scan_res = scan_skills(platform=plat_enum, config=cfg)
            matched = [s for s in scan_res.skills if s.name.lower() == skill.lower() or s.id.lower() == skill.lower()]
            if matched:
                skill_path = Path(matched[0].path)
            else:
                err_console.print(f"[bold red]ERR_SKILL_NOT_FOUND:[/bold red] Skill '{skill}' not found.")
                raise typer.Exit(code=2)

        ev_toggle = toggle_skill_mode(skill_path, target_mode, config_path=config)
        payload = {
            "skill_name": ev_toggle.skill_name,
            "platform": ev_toggle.platform,
            "old_mode": ev_toggle.old_mode.value,
            "new_mode": ev_toggle.new_mode.value,
            "success": ev_toggle.success,
            "error_message": ev_toggle.error_message,
        }

        def render():
            if ev_toggle.success:
                console.print(f"[bold green]Updated {ev_toggle.skill_name}:[/bold green] {ev_toggle.old_mode.value} -> [bold yellow]{ev_toggle.new_mode.value}[/bold yellow]")
            else:
                err_console.print(f"[bold red]Failed to toggle mode:[/bold red] {ev_toggle.error_message}")

        _output(payload, format, render)
        if not ev_toggle.success:
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    # 3. List skills and their execution modes
    scan_res = scan_skills(platform=plat_enum, custom_paths=paths, config=cfg)
    if skill:
        # Filter for the single requested skill
        skills_to_show = [s for s in scan_res.skills if s.name.lower() == skill.lower() or s.id.lower() == skill.lower() or s.path == str(Path(skill).resolve())]
        if not skills_to_show:
            err_console.print(f"[bold red]ERR_SKILL_NOT_FOUND:[/bold red] Skill '{skill}' not found.")
            raise typer.Exit(code=2)
    else:
        skills_to_show = scan_res.skills

    def render_list():
        table = Table(title="Skills Execution Modes")
        table.add_column("Skill Name", style="bold green")
        table.add_column("Platform", style="magenta")
        table.add_column("Mode", style="bold yellow")
        table.add_column("Path", style="dim")
        for s in skills_to_show:
            icon = "📌" if s.execution_mode == SkillExecutionMode.RESIDENT else "⚡"
            table.add_row(s.name, s.platform.value, f"{icon} {s.execution_mode.value}", s.path)
        console.print(table)
        console.print(f"Total: {len(skills_to_show)} skills")

    data = {
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "platform": s.platform.value,
                "execution_mode": s.execution_mode.value,
                "path": s.path,
            }
            for s in skills_to_show
        ]
    }
    _output(data, format, render_list)
    raise typer.Exit(code=0)


@app.command()
def tui(
    ctx: typer.Context,
    no_tui: bool = typer.Option(False, "--no-tui", help="Disable TUI and fallback to CLI output"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path"),
    platform: str = typer.Option("all", "--platform", "-p", help="Target platform"),
    paths: Optional[List[str]] = typer.Option(None, "--path", "--custom-paths", help="Custom paths to scan"),
):
    """Launch interactive Textual TUI dashboard (FR-10, FR-13, EC-11)."""
    # EC-11: Environment compatibility check (no TTY or --no-tui)
    if no_tui or not sys.stdin.isatty():
        console.print("[dim]Non-interactive environment or --no-tui specified. Safe fallback to CLI help.[/dim]")
        console.print(ctx.get_help())
        raise typer.Exit(code=0)

    try:
        from skill_manager.tui.app import SkillManagerApp
    except ImportError as ie:
        err_console.print(f"[bold red]TUI dependencies not available:[/bold red] {ie}")
        raise typer.Exit(code=1)

    cfg = load_config(config)
    try:
        plat_enum = PlatformType(platform.lower())
    except ValueError:
        plat_enum = PlatformType.ALL

    tui_app = SkillManagerApp(config=cfg, custom_paths=paths, platform=plat_enum)
    tui_app.run()
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()

