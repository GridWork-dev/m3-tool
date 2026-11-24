import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from m3_pipeline.refs.sources import DEFAULT_USER_AGENT

Tier = Literal["polite", "unblock"]


@dataclass(frozen=True)
class SellerConfig:
    id: str
    base_url: str
    tier: Tier
    currency: str = "USD"
    price_selectors: tuple[str, ...] = ()
    image_min_side_px: int = 800
    opted_out: bool = False
    note: str = ""


@dataclass(frozen=True)
class PricingConfig:
    user_agent: str
    sellers: Mapping[str, SellerConfig]


class ConfigError(ValueError):
    pass


class _Seller(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    tier: Tier
    currency: Literal["USD", "EUR"] = "USD"
    price_selectors: tuple[str, ...] = ()
    image_min_side_px: int = 800
    opted_out: bool = False
    note: str = ""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_agent: str = DEFAULT_USER_AGENT
    sellers: dict[str, _Seller]


def load_pricing(path: Path, env: Mapping[str, str] | None = None) -> PricingConfig:
    env = os.environ if env is None else env
    try:
        parsed = _Config.model_validate(tomllib.loads(path.read_text()))
    except (OSError, ValueError, ValidationError) as exc:
        raise ConfigError(f"{path}: {exc}") from None
    sellers: dict[str, SellerConfig] = {}
    for key, value in parsed.sellers.items():
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key):
            raise ConfigError(f"{path}: invalid seller id {key!r}")
        url = urlsplit(value.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ConfigError(f"{path}: {key}.base_url must be an HTTP URL without credentials")
        if value.image_min_side_px < 800:
            raise ConfigError(f"{path}: {key}.image_min_side_px must be >= 800")
        sellers[key] = SellerConfig(key, **value.model_dump())
    return PricingConfig(env.get("M3_PRICES_USER_AGENT") or parsed.user_agent, sellers)
