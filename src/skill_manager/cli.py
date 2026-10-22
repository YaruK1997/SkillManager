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
from skill_manager.models import PlatformType, VersionStatus

app = typer.Typer(
    name="skill-manager",
    help="Cross-platform Local AI Skills & Plugins Manager",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


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
    paths: Optional[List[str]] = typer.Option(None, "--path", help="Custom paths to scan"),
    depth: int = typer.Option(3, "--depth", "-d", help="Scan depth"),
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


if __name__ == "__main__":
    app()

