from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from m3_pipeline.config import load_settings
from m3_pipeline.prices.config import ConfigError, load_pricing
from m3_pipeline.prices.models import Observation


def config_file(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "pricing.toml"
    path.write_text(
        'user_agent = "test-agent"\n[sellers.example]\n'
        'base_url = "https://example.test"\ntier = "polite"\n' + extra
    )
    return path


def test_tier_must_be_polite_or_unblock(tmp_path: Path) -> None:
    path = config_file(tmp_path)
    path.write_text(path.read_text().replace('"polite"', '"invalid"'))
    with pytest.raises(ConfigError, match="tier"):
        load_pricing(path)


def test_opted_out_seller_parses(tmp_path: Path) -> None:
    assert load_pricing(config_file(tmp_path, "opted_out = true\n")).sellers["example"].opted_out


def test_env_user_agent_overrides_toml(tmp_path: Path) -> None:
    assert (
        load_pricing(config_file(tmp_path), {"M3_PRICES_USER_AGENT": "override"}).user_agent
        == "override"
    )


def test_shipped_pricing_toml_parses_and_covers_the_first_wave() -> None:
    cfg = load_pricing(load_settings().repo_root / "pipeline/pricing.toml", {})
    assert {k for k, v in cfg.sellers.items() if v.tier == "polite"} == {
        "turner-motorsports",
        "ecs-tuning",
        "fcp-euro",
    }
    assert {k for k, v in cfg.sellers.items() if v.tier == "unblock"} == {
        "apexwheels",
        "ebay",
        "amazon",
    }
    assert all(s.note and not s.price_selectors for s in cfg.sellers.values())


def test_observation_to_yaml_matches_price_observation_fields() -> None:
    obs = Observation(
        "fixture-wheel",
        None,
        "https://example.test/p",
        "example",
        Decimal("123.45"),
        "USD",
        date(2026, 11, 24),
    )
    assert list(obs.to_yaml()) == ["amount", "currency", "seller", "checked", "url"]
    assert obs.to_yaml() == {
        "amount": 123.45,
        "currency": "USD",
        "seller": "example",
        "checked": "2026-11-24",
        "url": "https://example.test/p",
    }
