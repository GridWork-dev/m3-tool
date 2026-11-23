from typing import Annotated

import typer

from m3_pipeline.assets import load_assets
from m3_pipeline.config import load_settings
from m3_pipeline.stages import REGISTRY, UnknownStageError, run_stage

app = typer.Typer(help="M3 asset pipeline.", no_args_is_help=True)


def _names(names: list[str]) -> str:
    return ", ".join(sorted(names)) or "(none)"


@app.command()
def run(
    asset_id: Annotated[str, typer.Argument(help="Asset id from pipeline/assets.toml.")],
    stage: Annotated[str, typer.Option("--stage", help="Registered stage to run.")],
) -> None:
    """Run one stage for one asset. Exits 0 when ok, 1 when not ok, 2 for an unknown name."""
    settings = load_settings()
    assets = load_assets(settings.repo_root / "pipeline" / "assets.toml")
    # Resolve the asset before the stage so a bad asset id is reported even for a missing stage.
    asset = assets.get(asset_id)
    if asset is None:
        typer.echo(f"unknown asset {asset_id!r}; known: {_names(list(assets))}", err=True)
        raise typer.Exit(code=2)
    try:
        result = run_stage(stage, asset, settings)
    except UnknownStageError:
        typer.echo(f"unknown stage {stage!r}; known: {_names(list(REGISTRY))}", err=True)
        raise typer.Exit(code=2) from None
    for message in result.messages:
        typer.echo(message, err=not result.ok)
    for output in result.outputs:
        typer.echo(str(output), err=not result.ok)
    raise typer.Exit(code=0 if result.ok else 1)


@app.command()
def stages() -> None:
    """List registered stages."""
    for name in sorted(REGISTRY):
        typer.echo(name)


@app.command()
def assets() -> None:
    """List assets from pipeline/assets.toml."""
    settings = load_settings()
    for spec in load_assets(settings.repo_root / "pipeline" / "assets.toml").values():
        typer.echo(f"{spec.id}\t{spec.kind}\t{spec.generation}\t{spec.subject}")
