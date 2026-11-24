import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Literal

import httpx
import typer

from m3_pipeline.config import load_settings
from m3_pipeline.refs.commons import CommonsClient
from m3_pipeline.refs.crawl.engine import crawl_pages
from m3_pipeline.refs.crawl.fetchers import MissingCredentials, open_fetcher
from m3_pipeline.refs.crawl.robots import RobotsCache
from m3_pipeline.refs.importer import import_directory
from m3_pipeline.refs.sources import SubjectSources, load_sources
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.subjects import parse_subject
from m3_pipeline.refs.throttle import Throttle

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


@refs_app.command()
def commons(
    subject: Annotated[str, typer.Option("--subject")],
    limit: Annotated[int | None, typer.Option(min=1)] = None,
) -> None:
    """Collect configured Commons categories and searches."""
    settings = load_settings()
    sources = load_sources(settings.repo_root / "pipeline/refs-sources.toml")
    configured = sources.subjects.get(subject, SubjectSources())
    if not configured.commons_categories and not configured.search_terms:
        typer.echo("no categories or search terms in pipeline/refs-sources.toml", err=True)
        raise typer.Exit(2)
    with httpx.Client(
        headers={"User-Agent": sources.user_agent},
        timeout=30,
        follow_redirects=True,
    ) as http:
        report = CommonsClient(
            http,
            RefStore(settings),
            sources=sources,
            throttle=Throttle(sources.commons.min_interval_s),
        ).collect(
            subject,
            configured.commons_categories,
            search_terms=configured.search_terms,
            limit=limit,
        )
    for key, value in asdict(report).items():
        typer.echo(f"{key}={value}")


@refs_app.command("import")
def import_photos(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    subject: Annotated[str, typer.Option("--subject")],
    source_note: Annotated[str, typer.Option("--source-note")],
    license_short: Annotated[str | None, typer.Option("--license")] = None,
) -> None:
    """Import local photos without changing the originals."""
    try:
        parse_subject(subject)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    report = import_directory(
        RefStore(load_settings()),
        directory,
        subject=subject,
        source_note=source_note,
        license_short=license_short,
    )
    typer.echo(f"added={report.added} known={report.known} skipped={len(report.skipped)}")
    for path, reason in report.skipped:
        typer.echo(f"skipped {path}: {reason}")


@refs_app.command()
def crawl(
    subject: Annotated[str, typer.Option("--subject")],
    url: Annotated[list[str] | None, typer.Option("--url")] = None,
    backend: Annotated[Literal["local", "browserbase"], typer.Option()] = "local",
    max_pages: Annotated[int | None, typer.Option(min=1)] = None,
    delay: Annotated[float | None, typer.Option(min=0)] = None,
) -> None:
    """Visit only configured or explicitly supplied seed URLs."""
    try:
        parse_subject(subject)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    settings = load_settings()
    sources = load_sources(settings.repo_root / "pipeline/refs-sources.toml")
    urls = url or sources.subjects.get(subject, SubjectSources()).crawl_urls
    if not urls:
        typer.echo("no crawl URLs in pipeline/refs-sources.toml; supply --url", err=True)
        raise typer.Exit(2)
    crawl_settings = replace(
        sources.crawl,
        max_pages=max_pages if max_pages is not None else sources.crawl.max_pages,
        delay_s=delay if delay is not None else sources.crawl.delay_s,
    )
    try:
        with httpx.Client(
            headers={"User-Agent": sources.user_agent},
            timeout=30,
            follow_redirects=True,
        ) as http:
            robots = RobotsCache(http, sources.user_agent)
            with open_fetcher(
                backend,
                user_agent=sources.user_agent,
                env=os.environ,
                http=http,
                allowed=robots.allowed,
            ) as fetcher:
                report = crawl_pages(
                    subject,
                    urls,
                    settings=crawl_settings,
                    user_agent=sources.user_agent,
                    fetcher=fetcher,
                    http=http,
                    store=RefStore(settings),
                    throttle=Throttle(crawl_settings.delay_s),
                    robots=robots,
                )
    except MissingCredentials as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    for key, value in asdict(report).items():
        if key in {"blocked", "disallowed"}:
            typer.echo(f"{key}={len(value)}")
            for entry in value:
                typer.echo(f"{key}: {entry}")
        else:
            typer.echo(f"{key}={value}")
    if backend == "browserbase":
        typer.echo("browserbase sessions used: 1")
