from dataclasses import replace
from datetime import date
from typing import Annotated

import typer

prices_app = typer.Typer(help="Collect and review weekly price observations.", no_args_is_help=True)


@prices_app.command("check")
def check_command(
    no_images: Annotated[bool, typer.Option("--no-images")] = False,
    seller: Annotated[str | None, typer.Option("--seller")] = None,
) -> None:
    """Check stored product URLs once per seven days; collect photos unless disabled."""
    import httpx

    from m3_pipeline.config import load_settings
    from m3_pipeline.prices.check import check_prices, save_report
    from m3_pipeline.prices.config import load_pricing
    from m3_pipeline.prices.fetch.brightdata import redact
    from m3_pipeline.stages.lib.spend import SpendDenied

    settings = load_settings()
    cfg = load_pricing(settings.repo_root / "pipeline/pricing.toml")
    if seller is not None:
        if seller not in cfg.sellers:
            typer.echo(f"unknown seller: {seller}", err=True)
            raise typer.Exit(2)
        cfg = replace(cfg, sellers={seller: cfg.sellers[seller]})
    store = None
    if not no_images:
        from m3_pipeline.refs.store import RefStore

        store = RefStore(settings)
    try:
        with httpx.Client(timeout=30) as http:
            report = check_prices(
                settings.repo_root / "data/parts",
                cfg=cfg,
                http=http,
                store=store,
                today=date.today(),
            )
        save_report(report)
        typer.echo(redact(report.render()))
    except SpendDenied as exc:
        typer.echo(redact(str(exc)), err=True)
        raise typer.Exit(1) from None


@prices_app.command("discover")
def discover_command(part: Annotated[str | None, typer.Option("--part")] = None) -> None:
    """Search for candidate product URLs in the work directory; review before adding any."""
    import json

    import httpx

    from m3_pipeline.config import load_settings
    from m3_pipeline.prices.config import load_pricing
    from m3_pipeline.prices.discover import discover_part_candidates
    from m3_pipeline.prices.fetch.brightdata import MissingCredentials, redact
    from m3_pipeline.stages.lib.spend import SpendDenied

    settings = load_settings()
    cfg = load_pricing(settings.repo_root / "pipeline/pricing.toml")
    try:
        with httpx.Client(timeout=30) as http:
            path = discover_part_candidates(
                settings.repo_root / "data/parts", cfg, http, today=date.today(), part_id=part
            )
        typer.echo(str(path))
        units = json.loads(path.read_text())["units"]["exa"]
        typer.echo(f"Ledger units: exa {units} searches")
    except (SpendDenied, MissingCredentials, RuntimeError, ValueError) as exc:
        typer.echo(redact(str(exc)), err=True)
        raise typer.Exit(1) from None


@prices_app.command("apply")
def apply_command(dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    """Apply the saved check report to part YAML, preserving unrelated content."""
    from m3_pipeline.config import load_settings
    from m3_pipeline.prices.apply import apply_observations
    from m3_pipeline.prices.check import read_report
    from m3_pipeline.prices.week import save_apply_result

    result = apply_observations(
        load_settings().repo_root / "data/parts", read_report(), dry_run=dry_run
    )
    if not dry_run:
        save_apply_result(result)
    for path in result.changed_files:
        typer.echo(str(path))


@prices_app.command("pr")
def pr_command(no_pr: Annotated[bool, typer.Option("--no-pr")] = False) -> None:
    """Commit applied price changes and publish a PR; --no-pr keeps everything local."""
    import os

    from m3_pipeline.prices.apply import ApplyResult
    from m3_pipeline.prices.check import read_report
    from m3_pipeline.prices.pr import open_pr
    from m3_pipeline.prices.week import read_apply_result

    report = read_report()
    result = read_apply_result()
    if result is None:
        result = ApplyResult()
    env = dict(os.environ)
    if no_pr:
        env["M3_PRICES_NO_PR"] = "1"
    url = open_pr(apply_result=result, report=report, today=date.today(), runner_env=env)
    typer.echo(url or "No PR published.")


@prices_app.command("week")
def week_command(
    no_images: Annotated[bool, typer.Option("--no-images")] = False,
    no_apply: Annotated[bool, typer.Option("--no-apply")] = False,
    no_pr: Annotated[bool, typer.Option("--no-pr")] = False,
    seller: Annotated[str | None, typer.Option("--seller")] = None,
) -> None:
    """Check, apply and open the weekly PR; skip steps to review locally."""
    import os

    import httpx

    from m3_pipeline.config import load_settings
    from m3_pipeline.prices.config import load_pricing
    from m3_pipeline.prices.fetch.brightdata import MissingCredentials, redact
    from m3_pipeline.prices.week import run_week
    from m3_pipeline.stages.lib.spend import SpendDenied

    settings = load_settings()
    cfg = load_pricing(settings.repo_root / "pipeline/pricing.toml")
    if seller:
        if seller not in cfg.sellers:
            typer.echo(f"unknown seller: {seller}", err=True)
            raise typer.Exit(2)
        cfg = replace(cfg, sellers={seller: cfg.sellers[seller]})
    store = None
    if not no_images:
        from m3_pipeline.refs.store import RefStore

        store = RefStore(settings)
    try:
        with httpx.Client(timeout=30) as http:
            result = run_week(
                settings.repo_root / "data/parts",
                cfg=cfg,
                http=http,
                store=store,
                today=date.today(),
                runner_env=os.environ,
                no_apply=no_apply,
                no_pr=no_pr,
            )
        typer.echo(redact(result.render()))
    except (SpendDenied, MissingCredentials, RuntimeError, ValueError) as exc:
        typer.echo(redact(str(exc)), err=True)
        raise typer.Exit(1) from None
