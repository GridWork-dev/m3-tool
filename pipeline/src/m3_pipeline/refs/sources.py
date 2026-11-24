import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_USER_AGENT = "m3-tool-refs/0.1 (+https://github.com/GridWork-dev/m3-tool)"


@dataclass(frozen=True)
class CommonsSettings:
    thumb_width: int = 1920
    min_interval_s: float = 3.0


@dataclass(frozen=True)
class CrawlSettings:
    delay_s: float = 3.0
    max_pages: int = 25
    min_side_px: int = 800


@dataclass(frozen=True)
class SubjectSources:
    commons_categories: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    crawl_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefsSources:
    user_agent: str
    commons: CommonsSettings
    crawl: CrawlSettings
    subjects: Mapping[str, SubjectSources]


class SourcesError(ValueError):
    pass


class _SourcesDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    http: dict[str, str] = Field(default_factory=dict)
    commons: CommonsSettings = Field(default_factory=CommonsSettings)
    crawl: CrawlSettings = Field(default_factory=CrawlSettings)
    subjects: dict[str, SubjectSources] = Field(default_factory=dict)


def load_sources(path: Path, env: Mapping[str, str] | None = None) -> RefsSources:
    env = os.environ if env is None else env
    try:
        with path.open("rb") as file:
            raw: dict[str, Any] = tomllib.load(file)
        doc = _SourcesDocument.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise SourcesError(f"{path}: {exc}") from exc
    if doc.commons.thumb_width not in {
        120,
        150,
        180,
        200,
        220,
        250,
        300,
        320,
        330,
        400,
        440,
        500,
        600,
        640,
        660,
        800,
        960,
        1024,
        1280,
        1920,
        3840,
    }:
        raise SourcesError(f"{path}: commons.thumb_width must be a standard step (1920 or 3840)")
    if doc.crawl.delay_s < 0 or doc.crawl.max_pages < 1 or doc.crawl.min_side_px < 1:
        raise SourcesError(f"{path}: crawl delay, max_pages or min_side_px out of range")
    return RefsSources(
        env.get("M3_REFS_USER_AGENT") or doc.http.get("user_agent") or DEFAULT_USER_AGENT,
        CommonsSettings(doc.commons.thumb_width, max(1.0, doc.commons.min_interval_s)),
        doc.crawl,
        doc.subjects,
    )
