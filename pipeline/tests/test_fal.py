"""Tests for the guarded fal client.

Nothing here makes a network call, reads a real key or touches the real spend journal. The three
network seams (`_post`, `_get`, `_download`) and the poll sleep are replaced by a scripted fake,
the key is a made-up string handed in through `env`, and the journal is a file under `tmp_path`.
`authorize` runs for real against a ledger written under a temporary repo root, so the order of
"guard first, network after" is tested against the real guard, not a stand-in.
"""

import base64
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import pytest
from PIL import Image

import m3_pipeline.stages.lib.fal as fal
from m3_pipeline.config import Settings
from m3_pipeline.stages.lib.fal import (
    CallResult,
    FalClient,
    FalError,
    PlannedCall,
    Reply,
)
from m3_pipeline.stages.lib.generators import (
    Generator,
    GeneratorRefused,
    PriceUnknown,
    load_generators,
)
from m3_pipeline.stages.lib.spend import LedgerRow, SpendDenied

REGISTRY = load_generators(Path(__file__).resolve().parents[1] / "generators.toml")
KEY = "test-key-id:test-key-secret-0123456789"
SESSION = "t7-test"
TODAY = date.today()
REQUEST_ID = "019a1b2c-3d4e-7f80-9a1b-2c3d4e5f6a7b"
GLB_URL = "https://v3b.fal.media/files/b/x/model.glb"
TEXTURE_URL = "https://v3b.fal.media/files/b/x/texture_0.png"
OBJ_URL = "https://v3b.fal.media/files/b/x/model.obj"

RODIN_RESULT: dict[str, object] = {
    "model_mesh": {"url": GLB_URL, "content_type": "model/gltf-binary", "file_name": "model.glb"},
    "model_meshes": [],
    "textures": [{"url": TEXTURE_URL, "content_type": "image/png", "file_name": "t0.png"}],
    "seed": 11,
}


def queue_urls(owner: str = "fal-ai", app: str = "hyper3d") -> dict[str, object]:
    base = f"https://queue.fal.run/{owner}/{app}/requests/{REQUEST_ID}"
    return {
        "status": "IN_QUEUE",
        "request_id": REQUEST_ID,
        "response_url": base,
        "status_url": f"{base}/status",
        "cancel_url": f"{base}/cancel",
    }


def reply(status: int, body: object | None = None, **headers: str) -> Reply:
    return Reply(status=status, headers=headers, json=body)


def completed(**extra: object) -> Reply:
    return reply(200, {"status": "COMPLETED", "request_id": REQUEST_ID, **extra})


def in_progress(status: str = "IN_PROGRESS") -> Reply:
    return reply(202, {"status": status, "request_id": REQUEST_ID})


@dataclass
class FakeFal:
    """Scripted stand-in for the network seams. Records every call it receives.

    `statuses` are served in order, the last one repeating; the result is one reply. A reply
    that is an exception is raised instead, like httpx would.
    """

    submit: Reply | BaseException = field(default_factory=lambda: reply(200, queue_urls()))
    statuses: list[Reply | BaseException] = field(default_factory=lambda: [completed()])
    result: Reply | BaseException = field(default_factory=lambda: reply(200, RODIN_RESULT))
    download_errors: dict[str, BaseException] = field(default_factory=dict[str, BaseException])
    posts: list[tuple[str, Mapping[str, str], dict[str, object]]] = field(
        default_factory=list[tuple[str, Mapping[str, str], dict[str, object]]]
    )
    gets: list[tuple[str, Mapping[str, str]]] = field(
        default_factory=list[tuple[str, Mapping[str, str]]]
    )
    downloads: list[str] = field(default_factory=list[str])
    sleeps: list[float] = field(default_factory=list[float])
    on_post: Callable[[], None] | None = None

    def post(
        self, url: str, *, headers: Mapping[str, str], content: bytes, timeout_s: float
    ) -> Reply:
        assert timeout_s > 0
        if self.on_post is not None:
            self.on_post()
        body: dict[str, object] = json.loads(content)
        self.posts.append((url, dict(headers), body))
        if isinstance(self.submit, BaseException):
            raise self.submit
        return self.submit

    def get(self, url: str, *, headers: Mapping[str, str], timeout_s: float) -> Reply:
        assert timeout_s > 0
        self.gets.append((url, dict(headers)))
        outcome = self.result
        if url.endswith("/status"):
            outcome = self.statuses[0]
            if len(self.statuses) > 1:
                self.statuses.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def download(self, url: str, dest: Path, *, timeout_s: float) -> None:
        assert timeout_s > 0
        self.downloads.append(url)
        if url in self.download_errors:
            raise self.download_errors[url]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"bytes of {url}".encode())

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fal, "_post", self.post)
        monkeypatch.setattr(fal, "_get", self.get)
        monkeypatch.setattr(fal, "_download", self.download)
        monkeypatch.setattr(fal, "_sleep", self.sleep)


@pytest.fixture(autouse=True)
def session_and_no_real_journal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M3_SPEND_SESSION", SESSION)

    def never(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("a test reached the real spend journal")

    monkeypatch.setattr(fal, "default_journal", never)

    def no_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a test reached a real network seam")

    for seam in ("_post", "_get", "_download"):
        monkeypatch.setattr(fal, seam, no_network)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeFal:
    scripted = FakeFal()
    scripted.install(monkeypatch)
    return scripted


@pytest.fixture
def journal(tmp_path: Path) -> Path:
    return tmp_path / "state" / "spend-journal.jsonl"


def write_ledger(settings: Settings, *rows: tuple[str, str]) -> Path:
    """The ledger under `settings.repo_root`: today's cap row, then one call row per (tag, cost)."""
    header = (
        "# Spend ledger\n\nProse.\n\n"
        "| Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    lines = [
        f"| {TODAY.isoformat()} | $50 (Phase 0 spike, 3D generation) | — | "
        f"cap approved by the user session:{SESSION} | — | 0.00 | 0.00 / 50.00 |\n"
    ]
    total = Decimal(0)
    for tag, cost in rows:
        total += Decimal(cost)
        lines.append(
            f"| {TODAY.isoformat()} | $50 (Phase 0 spike, 3D generation) | fal | "
            f"spike:{tag} test call | 1 | {cost} | {total:f} / 50.00 |\n"
        )
    path = settings.repo_root / "docs" / "spend-ledger.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "".join(lines), "utf-8")
    return path


def client(
    settings: Settings,
    journal: Path | None,
    *,
    env: Mapping[str, str] | None = None,
    registry: Mapping[str, Generator] = REGISTRY,
    poll_interval_s: float = 3.0,
    max_polls: int = 600,
) -> FalClient:
    environment = {"M3_FAL_KEY": KEY} if env is None else env
    return FalClient(
        settings,
        registry,
        env=environment,
        journal=journal,
        poll_interval_s=poll_interval_s,
        max_polls=max_polls,
    )


def make_image(path: Path, shade: int, fmt: str = "PNG") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), (shade, shade, shade)).save(path, format=fmt)
    return path


def planned(
    settings: Settings,
    *,
    tag: str = "gen-t7-1",
    generator: str = "rodin-2.5",
    slots: Sequence[str] = ("front_34", "rear_34"),
    options: Mapping[str, object] | None = None,
) -> PlannedCall:
    images = tuple(
        make_image(settings.work_dir / "in" / f"{tag}-{index}.png", 40 + index)
        for index, _ in enumerate(slots)
    )
    return PlannedCall(
        call_id=tag,
        generator=generator,
        images=images,
        slots=tuple(slots),
        mesh=None,
        options={} if options is None else options,
    )


def out_dir(settings: Settings) -> Path:
    return settings.work_dir / "out"


def entries(journal: Path) -> list[dict[str, object]]:
    found: list[dict[str, object]] = [json.loads(line) for line in journal.read_text().splitlines()]
    return found


def statuses(journal: Path, tag: str) -> list[object]:
    return [entry.get("status") for entry in entries(journal) if entry["tag"] == tag]


def decode(uri: object) -> bytes:
    assert isinstance(uri, str)
    match = re.fullmatch(r"data:[a-z0-9/.+-]+;base64,([A-Za-z0-9+/=]+)", uri)
    assert match, uri[:60]
    return base64.b64decode(match.group(1))


# --- the order: guard first, network after ---


def test_run_checks_the_guard_before_any_network_call(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings)  # no row for the tag
    with pytest.raises(SpendDenied, match="no ledger row"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert fake.posts == []
    assert fake.gets == []
    assert not journal.exists()


@pytest.mark.parametrize("error", [ValueError("boom"), OSError("disk"), KeyError("x")])
def test_any_exception_from_authorize_is_a_no_go_before_any_network_call(
    settings: Settings,
    journal: Path,
    fake: FakeFal,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    def broken(*_args: object, **_kwargs: object) -> LedgerRow:
        raise error

    monkeypatch.setattr(fal, "authorize", broken)
    with pytest.raises(SpendDenied):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert fake.posts == []
    assert fake.gets == []
    assert fake.downloads == []


def test_a_client_built_without_a_journal_calls_authorize_with_no_journal_session_today_or_cap(
    settings: Settings, fake: FakeFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def spy(*args: object, **kwargs: object) -> LedgerRow:
        seen.append((args, kwargs))
        raise SpendDenied("stop here: this test only watches the arguments")

    monkeypatch.setattr(fal, "authorize", spy)
    with pytest.raises(SpendDenied):
        client(settings, None).run(planned(settings, tag="gen-spy"), out_dir(settings))

    (args, kwargs) = seen[0]
    assert args == ("gen-spy", Decimal("0.40"))  # the tag and the price, nothing else
    assert kwargs == {"ledger": settings.repo_root / "docs" / "spend-ledger.md"}
    assert fake.posts == []


def test_the_guard_runs_and_journals_before_the_first_network_byte(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    at_post: list[list[object]] = []
    fake.on_post = lambda: at_post.append(statuses(journal, "gen-t7-1"))
    client(settings, journal).run(planned(settings), out_dir(settings))
    assert at_post == [["authorized"]]


def test_a_tag_authorizes_one_call_only_so_a_second_run_never_posts(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    client(settings, journal).run(planned(settings), out_dir(settings))
    with pytest.raises(SpendDenied, match="already"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1


# --- local refusals happen before the guard: they burn no tag ---


def refused_without_spend(settings: Settings, journal: Path, fake: FakeFal) -> None:
    assert fake.posts == []
    assert fake.gets == []
    assert not journal.exists(), "a local refusal must not authorize (and so burn) the tag"


def test_missing_key_names_m3_fal_key_only(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    for env in ({}, {"M3_FAL_KEY": ""}, {"M3_FAL_KEY": "   "}):
        with pytest.raises(FalError) as error:
            client(settings, journal, env=env).run(planned(settings), out_dir(settings))
        assert "M3_FAL_KEY is not set" in str(error.value)
        assert re.findall(r"[A-Z0-9_]*KEY[A-Z0-9_]*", str(error.value)) == ["M3_FAL_KEY"]
    refused_without_spend(settings, journal, fake)


def test_a_key_that_cannot_be_a_header_value_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    with pytest.raises(FalError, match="M3_FAL_KEY"):
        client(settings, journal, env={"M3_FAL_KEY": "has a space\n"}).run(
            planned(settings), out_dir(settings)
        )
    refused_without_spend(settings, journal, fake)


def test_image_count_is_checked_against_the_generator_limits(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.30"))
    four_plus_one = ("front", "side", "rear", "front_34", "front")
    with pytest.raises(GeneratorRefused, match="takes 2 to 4 images"):
        client(settings, journal).run(
            planned(settings, generator="tripo-h3.1", slots=four_plus_one), out_dir(settings)
        )
    with pytest.raises(GeneratorRefused, match="takes 1 image"):
        client(settings, journal).run(
            planned(settings, generator="trellis-2", slots=("front_34", "front_34")),
            out_dir(settings),
        )
    six = ("front_34", "rear_34", "side", "front", "rear", "front")
    with pytest.raises(GeneratorRefused, match="takes 1 to 5 images"):
        client(settings, journal).run(planned(settings, slots=six), out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_a_mesh_generator_takes_one_mesh_and_no_images(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    image = planned(settings, generator="tripo-segment", slots=("front",))
    with pytest.raises(GeneratorRefused, match="no images"):
        client(settings, journal).run(image, out_dir(settings))
    with pytest.raises(GeneratorRefused, match="needs a mesh"):
        client(settings, journal).run(
            PlannedCall("gen-t7-1", "tripo-segment", (), (), None, {}), out_dir(settings)
        )
    refused_without_spend(settings, journal, fake)


def test_a_mesh_generator_sends_the_mesh_as_a_data_uri_in_its_field(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    mesh = settings.work_dir / "in" / "body.glb"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"glTF mesh bytes")
    fake.submit = reply(200, queue_urls("tripo3d", "tripo"))
    fake.result = reply(200, {"model_mesh": {"url": GLB_URL}, "model_urls": {}})
    call = PlannedCall("gen-t7-1", "tripo-segment", (), (), mesh, {})
    client(settings, journal).run(call, out_dir(settings))
    (url, _headers, body) = fake.posts[0]
    assert url == "https://queue.fal.run/tripo3d/tripo/segment"
    assert set(body) == {"mesh_url"}
    assert decode(body["mesh_url"]) == b"glTF mesh bytes"
    assert str(body["mesh_url"]).startswith("data:model/gltf-binary;base64,")


def test_an_images_generator_refuses_a_mesh(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    mesh = settings.work_dir / "in" / "body.glb"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"glTF")
    call = PlannedCall("gen-t7-1", "rodin-2.5", (), (), mesh, {})
    with pytest.raises(GeneratorRefused, match="takes images, not a mesh"):
        client(settings, journal).run(call, out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_a_mesh_over_the_size_limit_is_refused_before_any_network_call(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    mesh = settings.work_dir / "in" / "huge.glb"
    mesh.parent.mkdir(parents=True)
    with mesh.open("wb") as handle:
        handle.truncate(150 * 1024 * 1024)  # a sparse 150 MiB file: nothing is read or stored
    call = PlannedCall("gen-t7-1", "tripo-segment", (), (), mesh, {})
    with pytest.raises(GeneratorRefused, match="150000000"):
        client(settings, journal).run(call, out_dir(settings))
    refused_without_spend(settings, journal, fake)


@pytest.mark.parametrize("name", ["empty.glb", "mesh.zip", "mesh"])
def test_an_empty_or_unknown_mesh_is_refused(
    settings: Settings, journal: Path, fake: FakeFal, name: str
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    mesh = settings.work_dir / "in" / name
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(b"" if name == "empty.glb" else b"x")
    with pytest.raises(GeneratorRefused):
        client(settings, journal).run(
            PlannedCall("gen-t7-1", "tripo-segment", (), (), mesh, {}), out_dir(settings)
        )
    refused_without_spend(settings, journal, fake)


def test_a_missing_input_file_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    call = planned(settings)
    call.images[0].unlink()
    with pytest.raises(GeneratorRefused, match="not a file"):
        client(settings, journal).run(call, out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_an_input_that_is_not_a_png_jpeg_or_webp_is_refused(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    call = planned(settings)
    call.images[0].write_bytes(b"GIF89a not an accepted image")
    with pytest.raises(GeneratorRefused, match="PNG, JPEG or WebP"):
        client(settings, journal).run(call, out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_inputs_inside_the_repo_are_never_uploaded(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    inside = make_image(settings.repo_root / "photo.png", 9)
    call = PlannedCall("gen-t7-1", "rodin-2.5", (inside,), ("front_34",), None, {})
    with pytest.raises(ValueError, match="inside the repo"):
        client(settings, journal).run(call, out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_an_out_dir_inside_the_repo_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    with pytest.raises(ValueError, match="inside the repo"):
        client(settings, journal).run(planned(settings), settings.repo_root / "out")
    refused_without_spend(settings, journal, fake)


@pytest.mark.parametrize("tag", ["../escape", "Gen_1", "gen 1", "", "gen--1", "gen-1/"])
def test_a_call_id_that_is_not_a_spend_tag_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal, tag: str
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    call = planned(settings)
    bad = PlannedCall(tag, call.generator, call.images, call.slots, None, {})
    with pytest.raises(GeneratorRefused, match="call id"):
        client(settings, journal).run(bad, out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_an_unknown_generator_is_refused(settings: Settings, journal: Path, fake: FakeFal) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    call = planned(settings)
    with pytest.raises(GeneratorRefused, match="unknown generator"):
        client(settings, journal).run(
            PlannedCall("gen-t7-1", "hi3d", call.images, call.slots, None, {}), out_dir(settings)
        )
    refused_without_spend(settings, journal, fake)


def test_a_registry_entry_pointing_outside_the_registry_set_is_refused(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    # `run` re-checks the endpoint against the registry it was given, so a hand-built entry that
    # names an open-weights Hunyuan or Hi3D endpoint cannot be called.
    import dataclasses

    write_ledger(settings, ("gen-t7-1", "0.40"))
    rogue = dataclasses.replace(REGISTRY["rodin-2.5"], endpoint="hitem3d/hi3d/split")
    with pytest.raises(GeneratorRefused, match="hitem3d/"):
        client(settings, journal, registry={"rodin-2.5": REGISTRY["rodin-2.5"], "x": rogue}).run(
            PlannedCall("gen-t7-1", "x", (), (), None, {}), out_dir(settings)
        )
    refused_without_spend(settings, journal, fake)


def test_an_option_with_no_price_rule_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "1.20"))
    call = planned(settings, generator="meshy-7.1", slots=("front", "side"))
    unpriced = PlannedCall(
        call.call_id, call.generator, call.images, call.slots, None, {"geometry_resolution": "2k"}
    )
    with pytest.raises(PriceUnknown, match="geometry_resolution"):
        client(settings, journal).run(unpriced, out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_a_request_over_fals_body_cap_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    monkeypatch.setattr(fal, "MAX_BODY_BYTES", 200)
    with pytest.raises(GeneratorRefused, match="64 MiB"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    refused_without_spend(settings, journal, fake)


# --- Hunyuan: host country, labeled fields, derived multi-view ---


HUNYUAN_SLOTS = ("front", "back", "left", "left-front 45")


def hunyuan_call(settings: Settings, options: Mapping[str, object] | None = None) -> PlannedCall:
    return planned(
        settings, tag="gen-t7-1", generator="hunyuan-3.1-pro", slots=HUNYUAN_SLOTS, options=options
    )


def test_hunyuan_without_a_host_country_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.525"))
    with pytest.raises(GeneratorRefused, match="M3_HOST_COUNTRY"):
        client(settings, journal).run(hunyuan_call(settings), out_dir(settings))
    refused_without_spend(settings, journal, fake)


@pytest.mark.parametrize("country", ["DE", "GB", "KR"])
def test_hunyuan_in_the_eu_uk_or_south_korea_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal, country: str
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.525"))
    env = {"M3_FAL_KEY": KEY, "M3_HOST_COUNTRY": country}
    with pytest.raises(GeneratorRefused, match="EU, UK or South Korea"):
        client(settings, journal, env=env).run(hunyuan_call(settings), out_dir(settings))
    refused_without_spend(settings, journal, fake)


def test_labeled_endpoint_sends_each_image_in_its_slot_field(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.525"))
    fake.submit = reply(200, queue_urls())
    fake.result = reply(200, {"model_glb": {"url": GLB_URL}, "model_urls": {}, "seed": 1})
    call = hunyuan_call(settings)
    env = {"M3_FAL_KEY": KEY, "M3_HOST_COUNTRY": "US"}
    client(settings, journal, env=env).run(call, out_dir(settings))

    (url, _headers, body) = fake.posts[0]
    assert url == "https://queue.fal.run/fal-ai/hunyuan-3d/v3.1/pro/image-to-3d"
    expected = {
        "input_image_url": call.images[0],
        "back_image_url": call.images[1],
        "left_image_url": call.images[2],
        "left_front_image_url": call.images[3],
    }
    for field_name, path in expected.items():
        assert decode(body[field_name]) == path.read_bytes(), field_name
    assert "image_urls" not in body
    # More than one image is multi-view, which fal bills: 0.375 + 0.15, priced without being asked.
    assert body["enable_pbr"] is False
    (authorized,) = (e for e in entries(journal) if e.get("status") == "authorized")
    assert authorized["price"] == "0.525"


def test_a_hunyuan_call_that_denies_multi_view_is_refused_before_the_guard(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.375"))
    env = {"M3_FAL_KEY": KEY, "M3_HOST_COUNTRY": "US"}
    with pytest.raises(GeneratorRefused, match="multi_view"):
        client(settings, journal, env=env).run(
            hunyuan_call(settings, {"multi_view": False}), out_dir(settings)
        )
    refused_without_spend(settings, journal, fake)


def test_a_hunyuan_ledger_row_below_the_multi_view_price_is_denied(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    # A row estimated for a single image does not cover four, so the guard denies it.
    write_ledger(settings, ("gen-t7-1", "0.375"))
    env = {"M3_FAL_KEY": KEY, "M3_HOST_COUNTRY": "US"}
    with pytest.raises(SpendDenied, match="below the price"):
        client(settings, journal, env=env).run(hunyuan_call(settings), out_dir(settings))
    assert fake.posts == []


# --- list endpoints: slot order, data URIs, JSON body ---


def test_list_endpoint_sends_images_in_slot_order(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    slots = ("rear", "front_34", "side")  # given out of order
    call = planned(settings, slots=slots)
    client(settings, journal).run(call, out_dir(settings))

    (url, _headers, body) = fake.posts[0]
    assert url == "https://queue.fal.run/fal-ai/hyper3d/rodin/v2.5"
    sent = cast(list[object], body["image_urls"])
    by_slot = dict(zip(slots, call.images, strict=True))
    assert [decode(uri) for uri in sent] == [
        by_slot[name].read_bytes() for name in ("front_34", "side", "rear")
    ]


@pytest.mark.parametrize(
    ("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_images_go_as_data_uris_with_their_real_type(
    settings: Settings, journal: Path, fake: FakeFal, fmt: str, mime: str
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    call = planned(settings, slots=("front_34",))
    make_image(call.images[0], 7, fmt)  # the extension stays .png: the bytes decide the type
    client(settings, journal).run(call, out_dir(settings))
    (_url, _headers, body) = fake.posts[0]
    sent = cast(list[object], body["image_urls"])
    assert str(sent[0]).startswith(f"data:{mime};base64,")


def test_the_options_become_fals_fields_in_the_body(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "1.20"))
    client(settings, journal).run(
        planned(settings, options={"highpack": True, "seed": 5}), out_dir(settings)
    )
    (_url, _headers, body) = fake.posts[0]
    assert body["addons"] == {"high_pack": True}
    assert body["seed"] == 5
    assert "highpack" not in body


def test_trellis_sends_one_image_as_a_plain_string(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.30"))
    fake.result = reply(200, {"model_glb": {"url": GLB_URL}})
    call = planned(settings, generator="trellis-2", slots=("front_34",))
    client(settings, journal).run(call, out_dir(settings))
    (_url, _headers, body) = fake.posts[0]
    assert decode(body["image_url"]) == call.images[0].read_bytes()
    assert body["resolution"] == 1024


# --- the key and the request headers ---


def test_run_sends_the_key_header_and_never_logs_it(
    settings: Settings,
    journal: Path,
    fake: FakeFal,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    write_ledger(settings, ("gen-t7-1", "0.40"))
    client(settings, journal).run(planned(settings), out_dir(settings))

    (_url, post_headers, _body) = fake.posts[0]
    assert post_headers["Authorization"] == f"Key {KEY}"
    assert post_headers["Content-Type"] == "application/json"
    assert post_headers["X-Fal-No-Retry"] == "1"
    assert fake.gets
    for _url, get_headers in fake.gets:
        assert get_headers["Authorization"] == f"Key {KEY}"
    assert KEY not in caplog.text
    assert "base64" not in caplog.text  # nor an image
    assert KEY not in journal.read_text()


@pytest.mark.parametrize("stage", ["submit", "status", "result"])
def test_an_error_body_that_echoes_the_key_is_scrubbed_from_the_message(
    settings: Settings, journal: Path, fake: FakeFal, stage: str
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    leak = {"detail": f"bad credentials Key {KEY}"}
    if stage == "submit":
        fake.submit = reply(401, leak)
    elif stage == "status":
        fake.statuses = [reply(401, leak)]
    else:
        fake.result = reply(500, leak)
    with pytest.raises(FalError) as error:
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert KEY not in str(error.value)
    assert KEY not in repr(error.value)
    assert "[redacted]" in str(error.value)
    assert KEY not in journal.read_text()


def test_downloads_never_carry_the_key(settings: Settings, journal: Path, fake: FakeFal) -> None:
    # The download seam takes no headers at all: fal's CDN urls are public.
    import inspect

    assert "headers" not in inspect.signature(fal._download).parameters  # pyright: ignore[reportPrivateUsage]


# --- the happy path: poll, fetch, download everything ---


def test_run_downloads_every_file_before_returning(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    result = client(settings, journal).run(planned(settings), out_dir(settings))

    assert isinstance(result, CallResult)
    assert result.call_id == "gen-t7-1"
    assert result.request_id == REQUEST_ID
    assert set(result.files) == {"model_mesh", "textures.0"}
    for path in result.files.values():
        assert path.is_file()
        assert path.parent == out_dir(settings)
    assert result.files["model_mesh"].read_bytes() == f"bytes of {GLB_URL}".encode()
    assert result.files["model_mesh"].suffix == ".glb"
    assert result.files["textures.0"].suffix == ".png"
    assert sorted(fake.downloads) == sorted([GLB_URL, TEXTURE_URL])
    # No temp or partial files are left behind.
    assert sorted(p.name for p in out_dir(settings).iterdir()) == sorted(
        p.name for p in result.files.values()
    )


def test_one_url_is_downloaded_once_and_named_by_the_result_field(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.result = reply(
        200,
        {
            "model_urls": {"glb": {"url": GLB_URL}, "obj": {"url": OBJ_URL}},
            "model_mesh": {"url": GLB_URL},
            "thumbnail": {"url": ""},  # an empty url is skipped
            "seed": 3,
        },
    )
    result = client(settings, journal).run(planned(settings), out_dir(settings))
    assert fake.downloads.count(GLB_URL) == 1
    assert fake.downloads[0] == GLB_URL  # the result field first: results expire in minutes
    assert result.files["model_mesh"] == result.files["model_urls.glb"]
    assert result.files["model_urls.obj"].suffix == ".obj"
    assert "thumbnail" not in result.files


def test_a_result_listing_too_many_files_is_a_failed_call_without_a_download(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    many = {
        f"file_{index}": {"url": f"https://v3b.fal.media/files/b/x/{index}.png"}
        for index in range(65)
    }
    fake.result = reply(200, {"model_mesh": {"url": GLB_URL}, **many})
    with pytest.raises(FalError, match="66 files"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert fake.downloads == []
    assert statuses(journal, "gen-t7-1")[-1] == "failed"


def test_file_names_come_from_the_call_and_the_key_never_from_fals_file_name(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.result = reply(
        200,
        {"model_mesh": {"url": GLB_URL, "file_name": "../../../etc/passwd"}},
    )
    result = client(settings, journal).run(planned(settings), out_dir(settings))
    (path,) = set(result.files.values())
    assert path.parent == out_dir(settings)
    assert path.name.startswith("gen-t7-1.model_mesh.")


def test_the_poll_waits_between_checks_and_never_posts_again(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [in_progress("IN_QUEUE"), in_progress(), in_progress(), completed()]
    client(settings, journal, poll_interval_s=2.0).run(planned(settings), out_dir(settings))
    status_gets = [url for url, _ in fake.gets if url.endswith("/status")]
    assert len(status_gets) == 4
    assert fake.sleeps == [2.0, 2.0, 2.0]
    assert len(fake.posts) == 1


def test_the_status_and_result_urls_are_the_ones_fal_returned(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    # fal: "Do not build these URLs yourself": the owner and app differ from the model id's path.
    write_ledger(settings, ("gen-t7-1", "0.40"))
    client(settings, journal).run(planned(settings), out_dir(settings))
    base = f"https://queue.fal.run/fal-ai/hyper3d/requests/{REQUEST_ID}"
    assert [url for url, _ in fake.gets] == [f"{base}/status", base]


def test_run_records_the_real_cost_as_a_decimal_under_cost_in_the_journal(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    result = client(settings, journal).run(planned(settings), out_dir(settings))

    assert isinstance(result.cost, Decimal)
    assert result.cost == Decimal("0.40")
    assert statuses(journal, "gen-t7-1") == ["authorized", "submitted", "succeeded"]
    *_, outcome = entries(journal)
    assert outcome["cost"] == "0.40"  # record_outcome writes a Decimal as a string, never a float
    assert outcome["request_id"] == REQUEST_ID
    assert outcome["generator"] == "rodin-2.5"
    assert outcome["files"] == {k: v.name for k, v in result.files.items()}


def test_a_billable_units_header_is_recorded_when_fal_sends_one(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.result = reply(200, RODIN_RESULT, **{"x-fal-billable-units": "1"})
    client(settings, journal).run(planned(settings), out_dir(settings))
    *_, outcome = entries(journal)
    assert outcome["billable_units"] == "1"


def test_a_cost_recorded_by_a_run_counts_against_the_cap_afterwards(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    from m3_pipeline.stages.lib.spend import authorize

    write_ledger(settings, ("gen-t7-1", "0.40"), ("gen-t7-2", "49.60"))
    client(settings, journal).run(planned(settings), out_dir(settings))
    # 0.40 spent, the second row would make exactly 50.00: allowed. The journal reads back clean.
    authorize(
        "gen-t7-2",
        Decimal("49.60"),
        ledger=settings.repo_root / "docs" / "spend-ledger.md",
        journal=journal,
    )


# --- failures after payment ---


def test_a_failed_request_is_journaled_and_raised_without_a_download(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [completed(error="Input rejected by the model", error_type="bad_request")]
    with pytest.raises(FalError, match="Input rejected by the model"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert statuses(journal, "gen-t7-1") == ["authorized", "submitted", "failed"]
    assert fake.downloads == []
    assert len(fake.posts) == 1
    *_, outcome = entries(journal)
    assert outcome["request_id"] == REQUEST_ID


def test_a_result_the_model_rejected_is_a_failed_call_never_a_resubmit(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.result = reply(422, {"detail": [{"loc": ["body", "image_urls"], "msg": "bad image"}]})
    with pytest.raises(FalError, match="422"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert statuses(journal, "gen-t7-1")[-1] == "failed"
    assert len(fake.posts) == 1


def test_a_result_without_the_result_field_is_a_failed_call(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.result = reply(200, {"seed": 1, "textures": []})
    with pytest.raises(FalError, match="model_mesh"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert statuses(journal, "gen-t7-1")[-1] == "failed"


def test_download_failure_keeps_result_urls_and_never_resubmits(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.download_errors[TEXTURE_URL] = httpx.ReadTimeout("slow cdn")
    with pytest.raises(FalError, match=r"resume\('gen-t7-1'"):
        client(settings, journal).run(planned(settings), out_dir(settings))

    assert len(fake.posts) == 1
    assert statuses(journal, "gen-t7-1") == ["authorized", "submitted", "download-failed"]
    *_, outcome = entries(journal)
    assert outcome["result_urls"] == {"model_mesh": GLB_URL, "textures.0": TEXTURE_URL}
    assert outcome["request_id"] == REQUEST_ID
    assert not list(out_dir(settings).glob("*.part"))

    # The urls are enough to finish: no status poll, no result fetch, no new submit.
    del fake.download_errors[TEXTURE_URL]
    gets_before = len(fake.gets)
    finished = client(settings, journal).resume("gen-t7-1", out_dir(settings))
    assert len(fake.posts) == 1
    assert len(fake.gets) == gets_before
    assert set(finished.files) == {"model_mesh", "textures.0"}
    assert statuses(journal, "gen-t7-1")[-1] == "succeeded"


@pytest.mark.parametrize(
    "url",
    [
        "http://v3b.fal.media/files/model.glb",
        "file:///etc/passwd",
        "data:text/plain;base64,AAAA",
        "https://localhost/model.glb",
        "https://127.0.0.1/model.glb",
        "https://user:pass@v3b.fal.media/model.glb",
        "//v3b.fal.media/model.glb",
    ],
)
def test_a_result_url_that_is_not_a_plain_https_host_is_never_fetched(
    settings: Settings, journal: Path, fake: FakeFal, url: str
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.result = reply(200, {"model_mesh": {"url": url}})
    with pytest.raises(FalError, match="https"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert fake.downloads == []
    assert statuses(journal, "gen-t7-1")[-1] == "download-failed"


# --- submit: a timeout is never retried ---


def test_submit_timeout_is_not_retried(settings: Settings, journal: Path, fake: FakeFal) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.submit = httpx.ReadTimeout("timed out")
    with pytest.raises(FalError, match="fal dashboard"):
        client(settings, journal).run(planned(settings), out_dir(settings))

    assert len(fake.posts) == 1
    assert fake.gets == []
    assert statuses(journal, "gen-t7-1") == ["authorized", "outcome-unknown"]
    *_, outcome = entries(journal)
    assert outcome["generator"] == "rodin-2.5"
    assert outcome["endpoint"] == "fal-ai/hyper3d/rodin/v2.5"
    # The tag stays spent: a second run with it is denied, and nothing was sent.
    with pytest.raises(SpendDenied, match="already"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.WriteTimeout("slow"), httpx.RemoteProtocolError("cut")],
)
def test_any_transport_error_on_submit_is_outcome_unknown_and_not_retried(
    settings: Settings, journal: Path, fake: FakeFal, error: httpx.HTTPError
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.submit = error
    with pytest.raises(FalError, match="fal dashboard"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1
    assert statuses(journal, "gen-t7-1")[-1] == "outcome-unknown"


@pytest.mark.parametrize("code", [500, 502, 503])
def test_a_server_error_on_submit_is_outcome_unknown_and_not_retried(
    settings: Settings, journal: Path, fake: FakeFal, code: int
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.submit = reply(code, {"detail": "try later"})
    with pytest.raises(FalError, match="fal dashboard"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1
    assert statuses(journal, "gen-t7-1")[-1] == "outcome-unknown"


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 422])
def test_a_client_error_on_submit_is_a_rejection_and_not_retried(
    settings: Settings, journal: Path, fake: FakeFal, code: int
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.submit = reply(code, {"detail": "no"})
    with pytest.raises(FalError, match=str(code)):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1
    assert statuses(journal, "gen-t7-1")[-1] == "submit-rejected"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "IN_QUEUE"},  # no request id
        {**queue_urls(), "status_url": "https://evil.example/status"},
        {**queue_urls(), "response_url": "http://queue.fal.run/x"},
        {**queue_urls(), "status_url": "https://queue.fal.run.evil.example/x/status"},
        {**queue_urls(), "status_url": "https://queue.fal.run@evil.example/x/status"},
        {**queue_urls(), "status_url": None},
    ],
)
def test_an_accepted_submit_without_usable_queue_urls_never_sends_the_key_elsewhere(
    settings: Settings, journal: Path, fake: FakeFal, body: dict[str, object]
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.submit = reply(200, body)
    with pytest.raises(FalError, match="queue.fal.run"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert fake.gets == []  # the key header never left for a host that is not fal's queue
    assert len(fake.posts) == 1
    assert statuses(journal, "gen-t7-1")[-1] == "outcome-unknown"


def test_the_backup_queue_host_is_accepted(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    urls = {
        k: (v.replace("queue.fal.run", "queue.falrun.com") if isinstance(v, str) else v)
        for k, v in queue_urls().items()
    }
    fake.submit = reply(200, urls)
    client(settings, journal).run(planned(settings), out_dir(settings))
    assert all(url.startswith("https://queue.falrun.com/") for url, _ in fake.gets)


# --- polling ---


def test_a_poll_that_never_completes_stops_and_points_at_resume(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [in_progress()]
    with pytest.raises(FalError, match=r"resume\('gen-t7-1'"):
        client(settings, journal, max_polls=3).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1
    assert statuses(journal, "gen-t7-1") == ["authorized", "submitted"]  # still in flight
    assert len([u for u, _ in fake.gets if u.endswith("/status")]) == 3


def test_transient_poll_errors_are_retried_a_few_times(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [httpx.ReadTimeout("t"), reply(503, {"detail": "x"}), completed()]
    client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1


def test_persistent_poll_errors_stop_and_point_at_resume(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [httpx.ConnectError("down")]
    with pytest.raises(FalError, match="resume"):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len(fake.posts) == 1


@pytest.mark.parametrize("code", [401, 403, 404])
def test_an_auth_or_lookup_error_while_polling_is_not_retried(
    settings: Settings, journal: Path, fake: FakeFal, code: int
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [reply(code, {"detail": "no"})]
    with pytest.raises(FalError, match=str(code)):
        client(settings, journal).run(planned(settings), out_dir(settings))
    assert len([u for u, _ in fake.gets if u.endswith("/status")]) == 1


# --- resume ---


def test_resume_polls_by_request_id_without_a_new_submit(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [in_progress()]
    with pytest.raises(FalError):
        client(settings, journal, max_polls=2).run(planned(settings), out_dir(settings))
    posts_before = len(fake.posts)
    fake.gets.clear()

    fake.statuses = [in_progress(), completed()]
    result = client(settings, journal).resume("gen-t7-1", out_dir(settings))

    assert len(fake.posts) == posts_before == 1  # never a second submit
    base = f"https://queue.fal.run/fal-ai/hyper3d/requests/{REQUEST_ID}"
    assert [url for url, _ in fake.gets] == [f"{base}/status", f"{base}/status", base]
    assert result.request_id == REQUEST_ID
    assert result.cost == Decimal("0.40")
    assert set(result.files) == {"model_mesh", "textures.0"}
    assert statuses(journal, "gen-t7-1") == ["authorized", "submitted", "succeeded"]
    *_, outcome = entries(journal)
    assert outcome["resumed"] is True


def test_resume_never_posts_even_when_the_submit_outcome_is_unknown(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.submit = httpx.ReadTimeout("t")
    with pytest.raises(FalError):
        client(settings, journal).run(planned(settings), out_dir(settings))
    with pytest.raises(FalError, match="no request id"):
        client(settings, journal).resume("gen-t7-1", out_dir(settings))
    assert len(fake.posts) == 1
    assert fake.gets == []


def test_resume_of_an_unknown_call_is_refused(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings)
    with pytest.raises(FalError, match="no authorization"):
        client(settings, journal).resume("gen-never", out_dir(settings))
    with pytest.raises(FalError, match="no authorization"):
        client(settings, journal).resume("gen-never", out_dir(settings))
    assert fake.posts == fake.gets == []


def test_resume_of_a_finished_call_is_refused(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    client(settings, journal).run(planned(settings), out_dir(settings))
    gets = len(fake.gets)
    with pytest.raises(FalError, match="already succeeded"):
        client(settings, journal).resume("gen-t7-1", out_dir(settings))
    assert len(fake.gets) == gets


def test_resume_of_a_failed_call_is_refused(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [completed(error="no", error_type="bad_request")]
    with pytest.raises(FalError):
        client(settings, journal).run(planned(settings), out_dir(settings))
    gets = len(fake.gets)
    with pytest.raises(FalError, match="failed"):
        client(settings, journal).resume("gen-t7-1", out_dir(settings))
    assert len(fake.gets) == gets


def test_resume_needs_the_key_and_a_clean_out_dir_target(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [in_progress()]
    with pytest.raises(FalError):
        client(settings, journal, max_polls=1).run(planned(settings), out_dir(settings))
    gets = len(fake.gets)
    with pytest.raises(FalError, match="M3_FAL_KEY is not set"):
        client(settings, journal, env={}).resume("gen-t7-1", out_dir(settings))
    with pytest.raises(ValueError, match="inside the repo"):
        client(settings, journal).resume("gen-t7-1", settings.repo_root / "out")
    assert len(fake.gets) == gets


def test_resume_refuses_a_journaled_endpoint_the_registry_no_longer_holds(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [in_progress()]
    with pytest.raises(FalError):
        client(settings, journal, max_polls=1).run(planned(settings), out_dir(settings))
    smaller = {key: gen for key, gen in REGISTRY.items() if key != "rodin-2.5"}
    gets = len(fake.gets)
    with pytest.raises(GeneratorRefused, match="rodin-2.5"):
        client(settings, journal, registry=smaller).resume("gen-t7-1", out_dir(settings))
    assert len(fake.gets) == gets


def test_resume_does_not_trust_journaled_urls_that_are_not_fals_queue(
    settings: Settings, journal: Path, fake: FakeFal
) -> None:
    write_ledger(settings, ("gen-t7-1", "0.40"))
    fake.statuses = [in_progress()]
    with pytest.raises(FalError):
        client(settings, journal, max_polls=1).run(planned(settings), out_dir(settings))
    text = journal.read_text().replace("queue.fal.run", "evil.example")
    journal.write_text(text)
    gets = len(fake.gets)
    with pytest.raises(FalError, match="queue.fal.run"):
        client(settings, journal).resume("gen-t7-1", out_dir(settings))
    assert len(fake.gets) == gets


# --- the seams themselves (no network: httpx is given a mock transport) ---


def test_the_default_seams_are_replaceable_module_functions() -> None:
    for name in ("_post", "_get", "_download", "_sleep"):
        assert callable(getattr(fal, name))


def test_reply_parses_json_and_tolerates_a_body_that_is_not_json() -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"a": 1})
            if request.url.path == "/json"
            else httpx.Response(502, text="<html>bad gateway</html>")
        )
    )
    with httpx.Client(transport=transport) as session:
        ok = fal.reply_from(session.get("https://queue.fal.run/json"))
        bad = fal.reply_from(session.get("https://queue.fal.run/html"))
    assert ok == Reply(status=200, headers=ok.headers, json={"a": 1})
    assert bad.status == 502
    assert bad.json is None


def test_the_real_download_streams_to_a_part_file_then_renames(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"abc" * 1000)

    dest = tmp_path / "out" / "file.glb"
    fal.download_with(
        httpx.Client(transport=httpx.MockTransport(handler)),
        "https://x.example/f",
        dest,
        timeout_s=5,
    )
    assert dest.read_bytes() == b"abc" * 1000
    assert [p.name for p in dest.parent.iterdir()] == ["file.glb"]


def test_the_real_download_leaves_nothing_behind_on_an_http_error(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, content=b"gone"))
    dest = tmp_path / "out" / "file.glb"
    with pytest.raises(httpx.HTTPStatusError):
        fal.download_with(
            httpx.Client(transport=transport), "https://x.example/f", dest, timeout_s=5
        )
    assert not dest.exists()
    assert not list(dest.parent.glob("*"))


def test_the_real_download_stops_at_the_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fal, "MAX_DOWNLOAD_BYTES", 100)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 1000))
    dest = tmp_path / "out" / "file.glb"
    with pytest.raises(OSError, match="100 bytes"):
        fal.download_with(
            httpx.Client(transport=transport), "https://x.example/f", dest, timeout_s=5
        )
    assert not list(dest.parent.glob("*"))
