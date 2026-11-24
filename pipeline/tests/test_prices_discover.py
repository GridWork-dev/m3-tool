import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest

from m3_pipeline.prices import exa
from m3_pipeline.prices.config import PricingConfig, SellerConfig
from m3_pipeline.prices.discover import discover_candidates

SELLER = SellerConfig("example", "https://example.test", "polite")
CFG = PricingConfig("test-agent", {"example": SELLER})


@pytest.fixture
def discover_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    parts = tmp_path / "data/parts"
    parts.mkdir(parents=True)
    (parts / "fixture-wheel.yaml").write_text(
        "id: fixture-wheel\nname: Fixture Wheel\nbrand: Fixture Co\n"
    )
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("M3_EXA_API_KEY", "test-key")

    def authorize(*args: object) -> None:
        pass

    monkeypatch.setattr(exa, "_authorize_fetch", authorize)
    return parts


def test_candidates_go_to_work_dir_never_data(discover_env: Path) -> None:
    before = {p: p.read_bytes() for p in discover_env.rglob("*") if p.is_file()}
    requests: list[httpx.Request] = []

    def respond(r: httpx.Request) -> httpx.Response:
        requests.append(r)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://example.test/wheel", "title": "Fixture Wheel"},
                    {"url": "https://unrelated.test/wheel", "title": "Wrong seller"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        path = discover_candidates(discover_env, CFG, http, today=date(2026, 11, 24))
    assert path == discover_env.parent.parent / "work/prices/candidates/2026-11-24.json"
    doc = json.loads(path.read_text())
    assert doc["candidates"][0]["part_id"] == "fixture-wheel"
    assert doc["candidates"][0]["seller"] == "example"
    assert doc["candidates"][0]["urls"] == ["https://example.test/wheel"]
    assert doc["units"] == {"exa": 1}
    assert {p: p.read_bytes() for p in discover_env.rglob("*") if p.is_file()} == before
    assert str(requests[0].url) == "https://api.exa.ai/search"
    assert requests[0].headers["x-api-key"] == "test-key"
    payload = json.loads(requests[0].content)
    assert payload == {
        "query": "Fixture Co Fixture Wheel fixture-wheel site:example.test",
        "numResults": 5,
        "type": "auto",
    }


def test_exa_key_never_logged(discover_env: Path, caplog: pytest.LogCaptureFixture) -> None:
    def fail(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x-api-key: test-key", request=r)

    with (
        httpx.Client(transport=httpx.MockTransport(fail)) as http,
        pytest.raises(RuntimeError) as exc,
    ):
        exa.exa_search(http, query="test", api_key="test-key")
    assert "test-key" not in str(exc.value) + caplog.text


def test_discover_skips_opted_out_sellers(discover_env: Path) -> None:
    cfg = replace(CFG, sellers={"example": replace(SELLER, opted_out=True)})
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: pytest.fail("opted-out seller searched"))
    ) as http:
        path = discover_candidates(discover_env, cfg, http, today=date(2026, 11, 24))
    assert json.loads(path.read_text())["candidates"] == []


def test_discover_part_filter_searches_only_that_part(discover_env: Path) -> None:
    from m3_pipeline.prices.discover import discover_part_candidates

    (discover_env / "fixture-other.yaml").write_text("id: fixture-other\nname: Other\n")
    queries: list[str] = []

    def respond(r: httpx.Request) -> httpx.Response:
        queries.append(json.loads(r.content)["query"])
        return httpx.Response(200, json={"results": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        discover_part_candidates(
            discover_env, CFG, http, today=date(2026, 11, 24), part_id="fixture-wheel"
        )
    assert len(queries) == 1 and "fixture-wheel" in queries[0]
