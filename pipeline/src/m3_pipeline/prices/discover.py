import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from m3_pipeline.config import load_settings
from m3_pipeline.prices.check import load_parts
from m3_pipeline.prices.config import PricingConfig
from m3_pipeline.prices.exa import exa_search
from m3_pipeline.prices.fetch.brightdata import credential


def discover_candidates(
    parts_dir: Path, cfg: PricingConfig, http: httpx.Client, *, today: date
) -> Path:
    return discover_part_candidates(parts_dir, cfg, http, today=today, part_id=None)


def discover_part_candidates(
    parts_dir: Path, cfg: PricingConfig, http: httpx.Client, *, today: date, part_id: str | None
) -> Path:
    parts = [part for _, part in load_parts(parts_dir) if part_id is None or part.id == part_id]
    if part_id is not None and not parts:
        raise ValueError(f"unknown part: {part_id}")
    candidates: list[dict[str, str | list[str]]] = []
    searches = 0
    for part in parts:
        for seller in cfg.sellers.values():
            if seller.opted_out:
                continue
            host = urlsplit(seller.base_url).hostname
            assert host is not None
            query = f"{part.brand} {part.name} {part.id} site:{host}".strip()
            results = exa_search(http, query=query, api_key=credential("M3_EXA_API_KEY"))
            searches += 1
            urls: list[str] = []
            for result in results:
                result_host = urlsplit(result.url).hostname or ""
                if (
                    result_host == host or result_host.endswith("." + host)
                ) and result.url not in urls:
                    urls.append(result.url)
            candidates.append(
                {
                    "part_id": part.id,
                    "seller": seller.id,
                    "urls": urls,
                    "note": (
                        "Unreviewed candidates. Verify product, option, currency and seller "
                        "before adding a URL."
                    ),
                }
            )
    path = load_settings().work_dir / f"prices/candidates/{today.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {"date": today.isoformat(), "units": {"exa": searches}, "candidates": candidates},
            indent=2,
        )
        + "\n"
    )
    temp.replace(path)
    return path
