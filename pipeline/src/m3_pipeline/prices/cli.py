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
