"""Tests for the `segment` stage.

Nothing here starts Blender, makes a network call, reads a real key or touches the real spend
journal. Blender is replaced at the one name `stages.lib.blender._run`, so the argv the stage
builds is the real one; the fal client is replaced at the stage's own seam `_fal_client` by a fake
that records what it was asked, except in the guard tests, which build a real `FalClient` over a
ledger and a journal under `tmp_path` and replace only its three network seams.
"""

import json
import struct
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import m3_pipeline.stages.lib.blender as blender_mod
import m3_pipeline.stages.lib.fal as fal_mod
import m3_pipeline.stages.lib.spend as spend_mod
import m3_pipeline.stages.segment as segment_mod
from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import REGISTRY, StageResult
from m3_pipeline.stages.lib.dims import load_dimensions
from m3_pipeline.stages.lib.fal import CallResult, FalClient, FalError, PlannedCall, Reply
from m3_pipeline.stages.lib.frames import box_to_blender
from m3_pipeline.stages.lib.generators import GeneratorRefused, load_generators
from m3_pipeline.stages.lib.placement import module_cut_planes
from m3_pipeline.stages.lib.spend import SpendDenied
from m3_pipeline.stages.segment import CONTRACT_PARTS, segment

ASSET = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")
REPO = Path(__file__).resolve().parents[2]
GENERATORS = load_generators(REPO / "pipeline" / "generators.toml")
BLENDER = "/fake/blender"
CANDIDATE = "gen-rodin-01"
CALL_ID = "seg-tripo-01"
FBX_BYTES = b"Kaydara FBX Binary  \x00\x1a\x00" + b"\x00" * 16
JSON_CHUNK = 0x4E4F534A

Box = tuple[tuple[float, float, float], tuple[float, float, float]]
BODY_BOX: Box = ((-0.89, 0.1, -2.2), (0.89, 1.0, 2.2))
GLASS_BOX: Box = ((-0.7, 1.0, -1.0), (0.7, 1.3, 0.6))
TRIM_BOX: Box = ((-0.8, 0.1, -2.2), (0.8, 0.5, 2.2))
PARTS: dict[str, tuple[int, Box]] = {
    "body": (60, BODY_BOX),
    "glass": (30, GLASS_BOX),
    "trim": (12, TRIM_BOX),
}
OTHER_PARTS: dict[str, tuple[int, Box]] = {"hood": (9, BODY_BOX), "door": (6, GLASS_BOX)}


def glb_bytes(parts: Mapping[str, tuple[int, Box]]) -> bytes:
    """A GLB with one named mesh node per part. Only the JSON chunk is real: `mesh_stats` and
    `part_stats` read nothing else."""
    nodes: list[dict[str, object]] = []
    meshes: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    for index, (name, (triangles, (low, high))) in enumerate(parts.items()):
        nodes.append({"name": name, "mesh": index})
        meshes.append({"primitives": [{"attributes": {"POSITION": index}}]})
        accessors.append(
            {
                "componentType": 5126,
                "count": 3 * triangles,
                "type": "VEC3",
                "min": list(low),
                "max": list(high),
            }
        )
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "accessors": accessors,
    }
    text = json.dumps(document).encode("utf-8")
    text += b" " * (-len(text) % 4)
    chunk = struct.pack("<II", len(text), JSON_CHUNK) + text
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk


@dataclass
class FakeBlender:
    """Stands in for the process runner under `run_blender`. Writes what each script would."""

    events: list[str]
    parts: Mapping[str, tuple[int, Box]] = field(default_factory=lambda: dict(PARTS))
    code: int = 0
    stderr: str = ""
    argvs: list[list[str]] = field(default_factory=list[list[str]])
    plans: dict[str, dict[str, object]] = field(default_factory=dict[str, dict[str, object]])

    def __call__(self, argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        args = list(argv)
        script = Path(args[args.index("-P") + 1]).name
        plan: dict[str, object] = json.loads(Path(args[args.index("--plan") + 1]).read_text())
        self.events.append(script)
        self.argvs.append(args)
        self.plans[script] = plan
        if self.code == 0:
            if script == "reduce_mesh.py":
                Path(str(plan["out_glb"])).write_bytes(b"reduced")
            elif script == "split_scripted.py":
                (Path(str(plan["out_dir"])) / "segmented.glb").write_bytes(glb_bytes(self.parts))
            elif script == "convert_to_glb.py":
                Path(str(plan["out_glb"])).write_bytes(glb_bytes(self.parts))
        return subprocess.CompletedProcess(args, self.code, "", self.stderr)


@dataclass
class FakeFal:
    """Stands in for `FalClient`: records each call and writes the files a result would hold."""

    events: list[str]
    files: dict[str, bytes] = field(default_factory=lambda: {"model_urls.glb": glb_bytes(PARTS)})
    run_error: BaseException | None = None
    resume_error: BaseException | None = None
    calls: list[PlannedCall] = field(default_factory=list[PlannedCall])
    resumed: list[str] = field(default_factory=list[str])

    def _result(self, call_id: str, out_dir: Path) -> CallResult:
        written: dict[str, Path] = {}
        for key, content in self.files.items():
            path = out_dir / f"{call_id}.{key}.bin"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            written[key] = path
        return CallResult(call_id, "req-1", written, Decimal("0.40"))

    def completed(self, call_id: str, out_dir: Path) -> CallResult | None:
        return None

    def run(self, call: PlannedCall, out_dir: Path) -> CallResult:
        self.events.append("fal")
        self.calls.append(call)
        assert call.mesh is not None
        assert call.mesh.is_file(), "the reduced copy must exist when the call is made"
        if self.run_error is not None:
            raise self.run_error
        return self._result(call.call_id, out_dir)

    def resume(self, call_id: str, out_dir: Path) -> CallResult:
        self.events.append("resume")
        self.resumed.append(call_id)
        if self.resume_error is not None:
            raise self.resume_error
        return self._result(call_id, out_dir)


@dataclass
class World:
    settings: Settings
    events: list[str]
    blender: FakeBlender
    fal: FakeFal
    monkeypatch: pytest.MonkeyPatch

    def use_blender(self, runner: Callable[..., subprocess.CompletedProcess[str]]) -> None:
        self.monkeypatch.setattr(blender_mod, "_run", runner)

    def stage(self, name: str = "") -> Path:
        base = self.settings.work_dir / "assets" / ASSET.id / "segment"
        return base / name if name else base

    def out(self, candidate: str = CANDIDATE, method: str = "tripo") -> Path:
        return self.stage(f"{candidate}/{method}")

    def prepare(self, candidate: str = CANDIDATE) -> Path:
        glb = self.settings.work_dir / "assets" / ASSET.id / "cleanup" / candidate / "prepared.glb"
        glb.parent.mkdir(parents=True, exist_ok=True)
        glb.write_bytes(b"prepared")
        return glb

    def plan(self, **fields: object) -> Path:
        document: dict[str, object] = {
            "candidate": CANDIDATE,
            "method": "tripo",
            "call_id": CALL_ID,
            "reduce_to_triangles": 150000,
        }
        document.update(fields)
        path = self.stage() / "plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), "utf-8")
        return path

    def run(self) -> StageResult:
        return segment(ASSET, self.settings)


def number(plan: Mapping[str, object], key: str) -> float:
    value = plan[key]
    assert isinstance(value, int | float) and not isinstance(value, bool), (key, value)
    return float(value)


def parts_json(directory: Path) -> dict[str, object]:
    document: dict[str, object] = json.loads((directory / "parts.json").read_text("utf-8"))
    return document


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """No process, no network, no real key, journal or session unless a test installs them."""
    monkeypatch.setenv("M3_BLENDER", BLENDER)
    monkeypatch.delenv("M3_SPEND_SESSION", raising=False)

    def no_process(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a test started a process")

    def no_client(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a test built the real fal client")

    def no_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a test reached a real network seam")

    def no_journal(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("a test reached the real spend journal")

    monkeypatch.setattr(blender_mod, "_run", no_process)
    monkeypatch.setattr(segment_mod, "_fal_client", no_client)
    for seam in ("_post", "_get", "_download"):
        monkeypatch.setattr(fal_mod, seam, no_network)
    monkeypatch.setattr(fal_mod, "default_journal", no_journal)
    monkeypatch.setattr(spend_mod, "default_journal", no_journal)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    events: list[str] = []
    blender = FakeBlender(events)
    fake = FakeFal(events)
    monkeypatch.setattr(blender_mod, "_run", blender)

    def fake_client(_settings: Settings) -> FakeFal:
        return fake

    monkeypatch.setattr(segment_mod, "_fal_client", fake_client)
    settings = Settings(repo_root=REPO, work_dir=tmp_path / "work")
    return World(settings, events, blender, fake, monkeypatch)


# --- registration and the plan ---


def test_segment_is_registered() -> None:
    assert REGISTRY["segment"] is segment


def test_segment_needs_a_plan(world: World) -> None:
    result = world.run()
    assert not result.ok
    assert "plan.json" in result.messages[0]


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"candidate": "../escape"}, "candidate"),
        ({"candidate": "Has Space"}, "candidate"),
        ({"candidate": 7}, "candidate"),
        ({"method": "hunyuan-part"}, "method"),
        ({"call_id": None}, "call_id"),
        ({"call_id": "Seg Tripo"}, "call_id"),
        ({"reduce_to_triangles": 0}, "reduce_to_triangles"),
        ({"reduce_to_triangles": True}, "reduce_to_triangles"),
        ({"reduce_to_triangles": "150000"}, "reduce_to_triangles"),
        ({"reduce": 100}, "reduce"),
    ],
)
def test_segment_refuses_a_plan_that_does_not_parse(
    world: World, fields: dict[str, object], match: str
) -> None:
    world.prepare()
    world.plan(**fields)
    result = world.run()
    assert not result.ok
    assert match in result.messages[0]
    assert world.events == []


@pytest.mark.parametrize("text", ["not json", "[1, 2]", ""])
def test_segment_refuses_a_plan_that_is_not_a_json_object(world: World, text: str) -> None:
    world.prepare()
    world.plan().write_text(text, "utf-8")
    result = world.run()
    assert not result.ok
    assert "plan.json" in result.messages[0]
    assert world.events == []


def test_segment_refuses_a_work_dir_inside_the_repo() -> None:
    inside = Settings(repo_root=REPO, work_dir=REPO / "t12-work-must-not-exist")
    result = segment(ASSET, inside)
    assert not result.ok
    assert "repo" in result.messages[0]
    assert not inside.work_dir.exists()


def test_segment_is_not_ok_when_the_candidate_is_unknown(world: World) -> None:
    world.plan(candidate="no-such-candidate")  # nothing under cleanup/
    result = world.run()
    assert not result.ok
    assert "cleanup/no-such-candidate/prepared.glb" in result.messages[0]
    assert "--stage cleanup" in result.messages[0]
    assert world.events == []


# --- tripo: through the guard, reduced first ---


def test_segment_tripo_goes_through_the_guard_with_a_ledger_row(world: World) -> None:
    world.prepare()
    world.plan()
    result = world.run()
    assert result.ok, result.messages
    assert world.fal.calls == [
        PlannedCall(
            call_id=CALL_ID,
            generator="tripo-segment",
            images=(),
            slots=(),
            mesh=world.out() / "reduced.glb",
            options={},
        )
    ]
    assert world.fal.resumed == []


def _ledger(repo: Path, tag: str, session: str, *, with_row: bool = True) -> None:
    day = date.today().isoformat()
    lines = [
        "# Spend ledger\n\n",
        "| Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap |\n",
        "|---|---|---|---|---|---|---|\n",
        f"| {day} | $50 (test) | — | cap approved by the user session:{session} | — | 0.00 |"
        " 0.00 / 50.00 |\n",
    ]
    if with_row:
        lines.append(
            f"| {day} | $50 (test) | fal | spike:{tag} Tripo segment | 1 | 0.40 | 0.40 / 50.00 |\n"
        )
    path = repo / "docs" / "spend-ledger.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), "utf-8")


QUEUE = "https://queue.fal.run/tripo3d/tripo/requests/req-9"
GLB_URL = "https://v3b.fal.media/files/x/segmented.glb"
FBX_URL = "https://v3b.fal.media/files/x/segmented.fbx"


@dataclass
class GuardWorld:
    world: World
    journal: Path
    posts: list[str]


@pytest.fixture
def guarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GuardWorld:
    """The real client and the real guard over a temporary repo, ledger and journal, with the
    three network seams replaced."""
    events: list[str] = []
    blender = FakeBlender(events)
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    journal = tmp_path / "state" / "spend-journal.jsonl"
    posts: list[str] = []

    def factory(configured: Settings) -> FalClient:
        return FalClient(
            configured, GENERATORS, env={"M3_FAL_KEY": "test-id:test-secret-0123456789"},
            journal=journal, poll_interval_s=0.0,
        )  # fmt: skip

    def post(url: str, **_kwargs: object) -> Reply:
        posts.append(url)
        body = {
            "request_id": "req-9",
            "status_url": f"{QUEUE}/status",
            "response_url": QUEUE,
        }
        return Reply(200, {}, body)

    def get(url: str, **_kwargs: object) -> Reply:
        if url.endswith("/status"):
            return Reply(200, {}, {"status": "COMPLETED"})
        # fal's documented output: `model_mesh` (GLB or FBX) and `model_urls` are both required.
        return Reply(
            200, {}, {"model_mesh": {"url": FBX_URL}, "model_urls": {"glb": {"url": GLB_URL}}}
        )

    def download(url: str, dest: Path, **_kwargs: object) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(glb_bytes(PARTS) if url == GLB_URL else FBX_BYTES)

    monkeypatch.setattr(blender_mod, "_run", blender)
    monkeypatch.setattr(segment_mod, "_fal_client", factory)
    monkeypatch.setattr(fal_mod, "_post", post)
    monkeypatch.setattr(fal_mod, "_get", get)
    monkeypatch.setattr(fal_mod, "_download", download)
    monkeypatch.setenv("M3_SPEND_SESSION", "t12-test")
    world = World(settings, events, blender, FakeFal(events), monkeypatch)
    return GuardWorld(world, journal, posts)


def _journal_statuses(journal: Path, tag: str) -> list[object]:
    entries = [json.loads(line) for line in journal.read_text("utf-8").splitlines()]
    return [
        entry["status"] for entry in cast("list[dict[str, object]]", entries) if entry["tag"] == tag
    ]


def test_segment_tripo_posts_once_through_the_real_guard_with_a_ledger_row(
    guarded: GuardWorld,
) -> None:
    world = guarded.world
    _ledger(world.settings.repo_root, CALL_ID, "t12-test")
    world.prepare()
    world.plan()
    result = world.run()
    assert result.ok, result.messages
    assert len(guarded.posts) == 1
    assert _journal_statuses(guarded.journal, CALL_ID) == ["authorized", "submitted", "succeeded"]
    # fal's `model_urls.glb`, as the real client names it, wins over an FBX `model_mesh`.
    assert "convert_to_glb.py" not in world.events
    assert [part["name"] for part in _parts(world.out())] == list(PARTS)


def test_segment_refuses_without_a_ledger_row(guarded: GuardWorld) -> None:
    world = guarded.world
    _ledger(world.settings.repo_root, CALL_ID, "t12-test", with_row=False)
    world.prepare()
    world.plan()
    result = world.run()
    assert not result.ok
    assert "no ledger row" in result.messages[0]
    assert guarded.posts == []  # not one network byte
    assert not guarded.journal.exists()  # and no tag was burned
    assert not (world.out() / "segmented.glb").exists()
    assert not (world.out() / "call.json").exists()  # nothing to resume: nothing was submitted


def test_segment_refuses_without_a_session_approval(
    guarded: GuardWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = guarded.world
    _ledger(world.settings.repo_root, CALL_ID, "t12-test")
    monkeypatch.delenv("M3_SPEND_SESSION")
    world.prepare()
    world.plan()
    result = world.run()
    assert not result.ok
    assert "M3_SPEND_SESSION" in result.messages[0]
    assert guarded.posts == []


def test_segment_reports_a_local_refusal_without_spending(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.run_error = GeneratorRefused("tripo-segment: the mesh is over the limit")
    result = world.run()
    assert not result.ok
    assert "over the limit" in result.messages[0]
    assert not (world.out() / "call.json").exists()


def test_segment_reduces_before_uploading(world: World) -> None:
    prepared = world.prepare()
    world.plan(reduce_to_triangles=120000)
    assert world.run().ok
    assert world.events[:2] == ["reduce_mesh.py", "fal"]
    plan = world.blender.plans["reduce_mesh.py"]
    assert plan == {
        "glb": str(prepared),
        "out_glb": str(world.out() / "reduced.glb"),
        "target_triangles": 120000,
    }


def test_segment_does_not_call_fal_when_the_reduction_fails(world: World) -> None:
    world.prepare()
    world.plan()
    world.blender.code = 1
    world.blender.stderr = "Traceback: no mesh"
    result = world.run()
    assert not result.ok
    assert "reduce_mesh.py exited 1" in result.messages[0]
    assert "no mesh" in result.messages[0]
    assert world.fal.calls == []


def test_segment_does_not_call_fal_when_blender_is_missing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.prepare()
    world.plan()
    monkeypatch.delenv("M3_BLENDER")
    monkeypatch.setenv("PATH", "")
    result = world.run()
    assert not result.ok
    assert "M3_BLENDER" in result.messages[0]
    assert world.fal.calls == []


def test_segment_does_not_call_fal_when_blender_times_out(world: World) -> None:
    world.prepare()
    world.plan()

    def hangs(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(list(argv), 1800)

    world.use_blender(hangs)
    result = world.run()
    assert not result.ok
    assert "timed out" in result.messages[0]
    assert world.fal.calls == []


def test_segment_does_not_call_fal_when_the_reduction_writes_nothing(world: World) -> None:
    world.prepare()
    world.plan()

    def writes_nothing(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    world.use_blender(writes_nothing)
    result = world.run()
    assert not result.ok
    assert "did not write" in result.messages[0]
    assert world.fal.calls == []


# --- tripo: picking the GLB ---


def _parts(directory: Path) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", parts_json(directory)["parts"])


def test_segment_lists_every_part_in_parts_json(world: World) -> None:
    world.prepare()
    world.plan()
    result = world.run()
    assert result.ok, result.messages
    document = parts_json(world.out())
    assert document["outcome"] == "ok"
    assert document["candidate"] == CANDIDATE
    assert document["method"] == "tripo"
    assert document["triangles"] == 60 + 30 + 12
    assert document["bbox_min"] == pytest.approx([-0.89, 0.1, -2.2])
    assert document["bbox_max"] == pytest.approx([0.89, 1.3, 2.2])
    parts = _parts(world.out())
    assert [part["name"] for part in parts] == ["body", "glass", "trim"]
    assert [part["triangles"] for part in parts] == [60, 30, 12]
    assert parts[1]["bbox_min"] == pytest.approx(list(GLASS_BOX[0]))
    assert parts[1]["bbox_max"] == pytest.approx(list(GLASS_BOX[1]))
    assert document["call_id"] == CALL_ID
    assert document["cost_usd"] == "0.40"


def test_segment_prefers_the_glb_in_model_urls(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {
        "model_mesh": glb_bytes(OTHER_PARTS),
        "model_urls.fbx": FBX_BYTES,
        "model_urls.glb": glb_bytes(PARTS),
    }
    result = world.run()
    assert result.ok, result.messages
    assert [part["name"] for part in _parts(world.out())] == list(PARTS)
    assert "convert_to_glb.py" not in world.events
    assert (world.out() / "segmented.glb").read_bytes() == glb_bytes(PARTS)


def test_segment_takes_model_mesh_when_it_is_a_glb_and_model_urls_has_none(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_mesh": glb_bytes(OTHER_PARTS)}
    result = world.run()
    assert result.ok, result.messages
    assert [part["name"] for part in _parts(world.out())] == list(OTHER_PARTS)
    assert "convert_to_glb.py" not in world.events


def test_segment_converts_fbx_to_glb_in_blender_when_no_glb_is_offered(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_mesh": FBX_BYTES}
    world.blender.parts = OTHER_PARTS
    result = world.run()
    assert result.ok, result.messages
    # The conversion ran before anything read the parts: the FBX itself has none to read.
    assert world.events == ["reduce_mesh.py", "fal", "convert_to_glb.py"]
    plan = world.blender.plans["convert_to_glb.py"]
    raw = world.out() / "raw" / f"{CALL_ID}.model_mesh.bin"
    assert plan == {"input": str(raw), "out_glb": str(world.out() / "segmented.glb")}
    assert [part["name"] for part in _parts(world.out())] == list(OTHER_PARTS)
    assert raw.read_bytes() == FBX_BYTES  # the paid file is kept


def test_segment_converts_a_model_urls_fbx_when_model_mesh_is_not_a_glb(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_mesh": b"?", "model_urls.fbx": FBX_BYTES}
    result = world.run()
    assert result.ok, result.messages
    plan = world.blender.plans["convert_to_glb.py"]
    assert str(plan["input"]).endswith(f"{CALL_ID}.model_urls.fbx.bin")


def test_segment_is_not_ok_when_the_conversion_fails_and_keeps_the_paid_files(
    world: World,
) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_mesh": FBX_BYTES}

    def fails_on_convert(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        script = Path(argv[list(argv).index("-P") + 1]).name
        if script == "convert_to_glb.py":
            world.events.append(script)
            return subprocess.CompletedProcess(list(argv), 1, "", "FBX import failed")
        return world.blender(argv, **kwargs)

    world.use_blender(fails_on_convert)
    result = world.run()
    assert not result.ok
    assert "convert_to_glb.py exited 1" in result.messages[0]
    assert (world.out() / "raw" / f"{CALL_ID}.model_mesh.bin").is_file()
    assert not (world.out() / "segmented.glb").exists()
    assert not (world.out() / "parts.json").exists()


def test_segment_records_an_unsupported_result_and_keeps_the_paid_files(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_mesh": b"PK\x03\x04 a zip", "textures.0": b"\x89PNG"}
    result = world.run()
    assert not result.ok
    assert "unsupported" in result.messages[0]
    assert str(world.out() / "raw") in result.messages[0]
    document = parts_json(world.out())
    assert document["outcome"] == "unsupported-result"
    assert document["files"] == {
        "model_mesh": f"raw/{CALL_ID}.model_mesh.bin",
        "textures.0": f"raw/{CALL_ID}.textures.0.bin",
    }
    assert sorted(path.name for path in (world.out() / "raw").iterdir()) == [
        f"{CALL_ID}.model_mesh.bin",
        f"{CALL_ID}.textures.0.bin",
    ]
    assert not (world.out() / "segmented.glb").exists()
    assert "convert_to_glb.py" not in world.events


def test_segment_is_not_ok_when_the_picked_glb_cannot_be_read_and_keeps_it(
    world: World,
) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_urls.glb": b"glTF but cut short"}
    result = world.run()
    assert not result.ok
    assert "segmented.glb" in result.messages[0]
    assert (world.out() / "raw" / f"{CALL_ID}.model_urls.glb.bin").is_file()


# --- a paid call is never repeated and never given a new tag ---


def test_a_resumable_failure_is_remembered_and_the_rerun_resumes_without_a_new_call(
    world: World,
) -> None:
    world.prepare()
    world.plan()
    world.fal.run_error = FalError(
        f"polling {CALL_ID} failed: resume({CALL_ID!r}, out_dir) polls it again", resumable=True
    )
    first = world.run()
    assert not first.ok
    assert f"resume({CALL_ID!r}" in first.messages[0]  # fal's own message, kept
    assert "re-run" in first.messages[0]
    assert json.loads((world.out() / "call.json").read_text()) == {
        "call_id": CALL_ID,
        "state": "pending",
    }

    world.fal.run_error = None
    second = world.run()
    assert second.ok, second.messages
    assert world.fal.resumed == [CALL_ID]
    assert [call.call_id for call in world.fal.calls] == [CALL_ID]  # run was not called again
    assert world.events.count("reduce_mesh.py") == 1  # and nothing was uploaded again
    assert parts_json(world.out())["outcome"] == "ok"


def test_a_resume_that_fails_again_stays_resumable_with_the_same_tag(world: World) -> None:
    world.prepare()
    world.plan()
    again = FalError("still not ready: resume('seg-tripo-01', out_dir)", resumable=True)
    world.fal.run_error = again
    world.fal.resume_error = again
    assert not world.run().ok
    assert not world.run().ok
    assert not world.run().ok
    assert world.fal.resumed == [CALL_ID, CALL_ID]
    assert len(world.fal.calls) == 1
    assert json.loads((world.out() / "call.json").read_text())["state"] == "pending"


def test_a_final_failure_leaves_nothing_to_resume_and_the_tag_unchanged(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.run_error = FalError("fal reports seg-tripo-01 failed: model crashed")
    assert not world.run().ok
    assert not (world.out() / "call.json").exists()
    # A second run asks the client again with the same tag, so the guard (which denies a tag
    # it has authorized) decides. The stage never picks another tag.
    world.fal.run_error = SpendDenied("tag 'seg-tripo-01' is already authorized")
    second = world.run()
    assert not second.ok
    assert "already authorized" in second.messages[0]
    assert [call.call_id for call in world.fal.calls] == [CALL_ID, CALL_ID]
    assert world.fal.resumed == []


def test_a_resume_the_client_refuses_is_reported_with_its_own_message(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.run_error = FalError("poll: resume('seg-tripo-01', out_dir)", resumable=True)
    assert not world.run().ok
    world.fal.resume_error = FalError("call 'seg-tripo-01' failed: a new call needs a new tag")
    result = world.run()
    assert not result.ok
    assert "needs a new tag" in result.messages[0]
    assert len(world.fal.calls) == 1


def test_an_interrupted_call_is_remembered_so_the_rerun_resumes_it(world: World) -> None:
    # Ctrl-C while the call is polling: without a record, the next `run` is denied by the guard
    # (the tag is spent) and its advice is a new tag, which would pay twice for one request.
    world.prepare()
    world.plan()
    world.fal.run_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        world.run()
    assert json.loads((world.out() / "call.json").read_text())["state"] == "pending"

    world.fal.run_error = None
    assert world.run().ok
    assert world.fal.resumed == [CALL_ID]
    assert len(world.fal.calls) == 1


def test_an_interrupt_before_any_call_leaves_no_record(world: World) -> None:
    world.prepare()
    world.plan()

    def interrupted(_argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise KeyboardInterrupt

    world.use_blender(interrupted)
    with pytest.raises(KeyboardInterrupt):
        world.run()
    assert not (world.out() / "call.json").exists()
    assert world.fal.calls == []


def test_a_refused_resume_names_the_record_to_delete_and_keeps_it(world: World) -> None:
    world.prepare()
    world.plan()
    world.fal.run_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        world.run()
    world.fal.resume_error = FalError("the journal has no authorization for 'seg-tripo-01'")
    result = world.run()
    assert not result.ok
    assert "no authorization" in result.messages[0]
    assert str(world.out() / "call.json") in result.messages[0]
    assert (world.out() / "call.json").is_file()  # only a person deletes it


def test_a_new_call_id_in_the_plan_starts_a_new_call_instead_of_resuming_the_old_one(
    world: World,
) -> None:
    world.prepare()
    world.plan()
    world.fal.run_error = FalError("poll: resume('seg-tripo-01', out_dir)", resumable=True)
    assert not world.run().ok
    world.fal.run_error = None
    world.plan(call_id="seg-tripo-02")
    assert world.run().ok
    assert world.fal.resumed == []
    assert [call.call_id for call in world.fal.calls] == ["seg-tripo-01", "seg-tripo-02"]


def test_a_rerun_after_a_paid_success_reuses_the_raw_files_and_never_calls_fal_again(
    world: World,
) -> None:
    world.prepare()
    world.plan()
    world.fal.files = {"model_mesh": FBX_BYTES}

    def fails_on_convert(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        script = Path(argv[list(argv).index("-P") + 1]).name
        if script == "convert_to_glb.py":
            return subprocess.CompletedProcess(list(argv), 1, "", "FBX import failed")
        return world.blender(argv, **kwargs)

    world.use_blender(fails_on_convert)
    assert not world.run().ok
    state = json.loads((world.out() / "call.json").read_text())
    assert state["state"] == "done"
    assert state["files"] == {"model_mesh": f"{CALL_ID}.model_mesh.bin"}

    world.use_blender(world.blender)  # Blender is fixed
    world.blender.parts = OTHER_PARTS
    result = world.run()
    assert result.ok, result.messages
    assert len(world.fal.calls) == 1
    assert world.fal.resumed == []
    assert world.events.count("reduce_mesh.py") == 1
    assert parts_json(world.out())["cost_usd"] == "0.40"


def test_a_call_record_whose_files_are_gone_is_reported_and_not_paid_for_again(
    world: World,
) -> None:
    world.prepare()
    world.plan()
    assert world.run().ok
    for path in (world.out() / "raw").iterdir():
        path.unlink()
    result = world.run()
    assert not result.ok
    assert "raw" in result.messages[0]
    assert len(world.fal.calls) == 1


def test_a_corrupt_call_record_stops_the_stage(world: World) -> None:
    world.prepare()
    world.plan()
    world.out().mkdir(parents=True)
    (world.out() / "call.json").write_text("{not json", "utf-8")
    result = world.run()
    assert not result.ok
    assert "call.json" in result.messages[0]
    assert world.fal.calls == []


# --- scripted ---


def test_segment_scripted_runs_blender_with_the_plan_json(world: World) -> None:
    prepared = world.prepare()
    world.plan(method="scripted", call_id=None)
    result = world.run()
    assert result.ok, result.messages
    out = world.out(method="scripted")
    assert world.blender.argvs == [
        [
            BLENDER,
            "-b",
            "--factory-startup",
            "-P",
            str(REPO / "pipeline" / "blender" / "split_scripted.py"),
            "--",
            "--plan",
            str(out / "split-plan.json"),
        ]
    ]
    plan = json.loads((out / "split-plan.json").read_text())
    assert plan["glb"] == str(prepared)
    assert plan["out_dir"] == str(out)
    assert world.fal.calls == []  # the fallback is free


def test_scripted_needs_no_call_id_and_ignores_one(world: World) -> None:
    world.prepare()
    world.plan(method="scripted")  # keeps the tripo call id
    assert world.run().ok
    assert world.fal.calls == []


def test_scripted_plan_holds_only_blender_frame_numbers(world: World) -> None:
    world.prepare()
    world.plan(method="scripted", call_id=None)
    assert world.run().ok
    plan = world.blender.plans["split_scripted.py"]
    unsuffixed = {
        "glb",
        "out_dir",
        "dark_luminance_max",
        "bright_luminance_min",
        "red_min",
        "red_dominance",
    }
    assert {key for key in plan if not key.endswith("_blender")} == unsuffixed
    assert not any("contract" in key for key in plan)
    # Color thresholds are luminances in [0, 1], dark below bright.
    assert 0 < number(plan, "dark_luminance_max") < number(plan, "bright_luminance_min") <= 1

    dims = load_dimensions(REPO, "e46", "coupe")
    height = dims.height_mm / 1000
    half = dims.length_mm / 2000
    contract = module_cut_planes(dims)
    modules = cast("dict[str, dict[str, list[float]]]", plan["modules_blender"])
    assert list(modules) == ["bumper_front", "bumper_rear", "trunk_lid", "roof"]
    for name, box in contract.items():
        converted = box_to_blender(box)
        assert modules[name] == {"min": list(converted.min), "max": list(converted.max)}
        # The mapping by hand, so the check does not rest on `frames` alone: x stays, the
        # contract's up (y) becomes z, and its z (nose at -z) becomes -y (nose at +y).
        assert modules[name]["min"] == pytest.approx([box.min[0], -box.max[2], box.min[1]])
        assert modules[name]["max"] == pytest.approx([box.max[0], -box.min[2], box.max[1]])
    # Blender frame: the nose is at +y and height is z.
    assert modules["bumper_front"]["min"][1] > 0 > modules["bumper_rear"]["max"][1]
    assert modules["roof"]["max"][2] > height
    assert number(plan, "undercarriage_z_max_blender") == pytest.approx(0.35)
    assert number(plan, "undercarriage_normal_z_max_blender") == pytest.approx(-0.7)
    belt = number(plan, "belt_line_z_blender")
    assert 0.5 * height < belt < height
    assert 0 < number(plan, "front_band_y_min_blender") < half
    assert -half < number(plan, "rear_band_y_max_blender") < 0
    assert number(plan, "grille_x_max_blender") > 0
    assert 0 < number(plan, "grille_z_max_blender") < belt


def test_scripted_stage_is_not_ok_when_the_generation_has_no_dimensions(world: World) -> None:
    unknown = AssetSpec("zz-coupe-body", "base-car", "zz", "zz-coupe")
    prepared = world.settings.work_dir / "assets" / unknown.id / "cleanup" / CANDIDATE
    prepared.mkdir(parents=True)
    (prepared / "prepared.glb").write_bytes(b"prepared")
    plan = world.settings.work_dir / "assets" / unknown.id / "segment" / "plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"candidate": CANDIDATE, "method": "scripted"}), "utf-8")
    result = segment(unknown, world.settings)
    assert not result.ok
    assert "zz.yaml" in result.messages[0]
    assert world.blender.argvs == []


def test_scripted_stage_is_not_ok_when_blender_exits_nonzero_or_writes_nothing(
    world: World,
) -> None:
    world.prepare()
    world.plan(method="scripted", call_id=None)
    world.blender.code = 1
    world.blender.stderr = "ValueError: boom"
    failed = world.run()
    assert not failed.ok
    assert "split_scripted.py exited 1" in failed.messages[0]
    assert "boom" in failed.messages[0]

    def writes_nothing(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    world.use_blender(writes_nothing)
    silent = world.run()
    assert not silent.ok
    assert "did not write" in silent.messages[0]


# --- outputs ---


def test_segment_outputs_include_the_candidate_and_the_method(world: World) -> None:
    seen: set[Path] = set()
    for tag, (candidate, method) in enumerate(
        [("cand-a", "tripo"), ("cand-a", "scripted"), ("cand-b", "tripo"), ("cand-b", "scripted")],
        start=1,
    ):
        world.prepare(candidate)
        world.plan(candidate=candidate, method=method, call_id=f"seg-tripo-0{tag}")
        result = world.run()
        assert result.ok, result.messages
        directory = world.out(candidate, method)
        assert directory == world.stage() / candidate / method
        assert (directory / "segmented.glb") in result.outputs
        assert (directory / "parts.json") in result.outputs
        seen.add(directory)
    assert len(seen) == 4
    for directory in seen:  # none was overwritten by a later one
        assert (directory / "segmented.glb").is_file()
        assert parts_json(directory)["candidate"] == directory.parent.name
        assert parts_json(directory)["method"] == directory.name


def test_both_methods_write_segmented_glb_in_their_own_directory(world: World) -> None:
    world.prepare()
    world.plan()
    tripo = world.run()
    world.plan(method="scripted", call_id=None)
    scripted = world.run()
    assert tripo.ok and scripted.ok
    assert (world.out(method="tripo") / "segmented.glb") in tripo.outputs
    assert (world.out(method="scripted") / "segmented.glb") in scripted.outputs
    assert (world.out(method="tripo") / "segmented.glb").is_file()
    assert (world.out(method="scripted") / "segmented.glb").is_file()
    assert not (world.stage() / CANDIDATE / "segmented.glb").exists()


def test_segment_reports_which_contract_parts_are_missing_but_still_writes_parts_json(
    world: World,
) -> None:
    world.prepare()
    world.plan(method="scripted", call_id=None)
    world.blender.parts = {name: PARTS["body"] for name in ("body", "roof", "glass", "grille")}
    result = world.run()
    assert result.ok, result.messages  # a partial split is a result, not a failure
    document = parts_json(world.out(method="scripted"))
    assert document["contract_parts_missing"] == [
        "bumper_front",
        "bumper_rear",
        "trunk_lid",
        "lights_front",
        "lights_rear",
        "trim",
        "undercarriage",
    ]
    assert document["contract_parts_found"] == ["body", "roof", "glass", "grille"]
    assert "missing contract parts: bumper_front" in " ".join(result.messages)


def test_contract_parts_are_body_four_modules_and_the_six_part_materials() -> None:
    assert CONTRACT_PARTS == (
        "body",
        "bumper_front",
        "bumper_rear",
        "trunk_lid",
        "roof",
        "glass",
        "lights_front",
        "lights_rear",
        "trim",
        "grille",
        "undercarriage",
    )


def test_segment_removes_the_outputs_of_an_earlier_run_before_it_starts(world: World) -> None:
    world.prepare()
    world.plan(method="scripted", call_id=None)
    out = world.out(method="scripted")
    out.mkdir(parents=True)
    (out / "segmented.glb").write_bytes(b"old")
    (out / "parts.json").write_text('{"outcome": "ok"}', "utf-8")
    world.blender.code = 1
    assert not world.run().ok
    assert not (out / "segmented.glb").exists()
    assert not (out / "parts.json").exists()


@pytest.mark.parametrize("pending", [False, True])
def test_completed_call_recovers_after_record_write_failure(
    guarded: GuardWorld, monkeypatch: pytest.MonkeyPatch, pending: bool
) -> None:
    world = guarded.world
    world.prepare()
    world.plan()
    _ledger(world.settings.repo_root, CALL_ID, "t12-test")
    original = Path.replace

    def fail_record(path: Path, target: Path) -> Path:
        if target.name == "call.json":
            raise OSError("record disk interruption")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_record)
    assert not world.run().ok
    assert _journal_statuses(guarded.journal, CALL_ID)[-1] == "succeeded"
    monkeypatch.setattr(Path, "replace", original)
    if pending:
        (world.out() / "call.json").write_text(json.dumps({"call_id": CALL_ID, "state": "pending"}))

    def no_key(_client: FalClient) -> str:
        raise AssertionError("completed recovery requested credentials")

    monkeypatch.setattr(FalClient, "_key", no_key)
    assert world.run().ok
    assert len(guarded.posts) == 1
    assert world.events.count("reduce_mesh.py") == 1


@pytest.mark.parametrize("timeout", [False, True])
def test_failed_blender_discards_output_written_before_failure(world: World, timeout: bool) -> None:
    world.prepare()
    world.plan(method="scripted")
    out = world.out(method="scripted")

    def partial(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        (out / "segmented.glb").write_bytes(glb_bytes(PARTS))
        if timeout:
            raise subprocess.TimeoutExpired(list(argv), 1)
        return subprocess.CompletedProcess(list(argv), 1, "", "after export")

    world.use_blender(partial)
    assert not world.run().ok
    assert not (out / "segmented.glb").exists()
