import typer

from m3_pipeline.config import load_settings
from m3_pipeline.refs.store import RefStore

refs_app = typer.Typer(help="Reference photo collection and curation")


@refs_app.command()
def stats() -> None:
    """Count reference records by subject and status."""
    store = RefStore(load_settings())
    for subject in sorted({r.subject for r in store.records()}):
        records = store.records(subject)
        counts = {s: sum(r.status == s for r in records) for s in ("new", "labeled", "duplicate")}
        typer.echo(
            f"{subject} images={len(records)} new={counts['new']} "
            f"labeled={counts['labeled']} duplicate={counts['duplicate']}"
        )
