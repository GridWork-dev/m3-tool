"""Offline synthesis orchestration tests: every inference and upload is replaced."""

import importlib
import json

import pytest
from PIL import Image

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages.lib.critic import Issue, Verdict
from m3_pipeline.stages.lib.provenance import load_provenance
from m3_pipeline.stages.lib.viewset_io import SpikeViewSet, ViewRef

stage = importlib.import_module("m3_pipeline.stages.synth")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"
    root = work / "assets/e46-body/synth"
    root.mkdir(parents=True)
    refs = []
    for name, view in (("a", "front_34_left"), ("b", "rear_34_right")):
        path = work / f"{name}.png"
        Image.new("RGB", (30, 20), "white").save(path)
        refs.append(
            ViewRef(
                view,
                name,
                path,
                None,
                False,
                "CC0",
                None,
                None,
                "https://commons.wikimedia.org/wiki/Test",
                "left",
                None,
                False,
            )
        )
    monkeypatch.setattr(
        stage, "load_viewset", lambda *_: SpikeViewSet("e46-coupe", "base-car", tuple(refs), {})
    )
    monkeypatch.setattr(stage, "load_dimensions", lambda *_: "4492 x 1780 x 1372")
    inputs = root.parent / "inputs"
    inputs.mkdir()
    (inputs / "redactions.json").write_text(json.dumps({"a": [], "b": []}))
    plan = {
        "views": {"side": {"inputs": ["a", "b"], "engine": "codex", "prompt_extra": "EXTRA"}},
        "reviewed_inputs": ["a", "b"],
    }
    (root / "plan.json").write_text(json.dumps(plan))
    calls = []

    def codex(prompt, images, *, cwd, last_message):
        calls.append((prompt, images, cwd, last_message))
        Image.new("RGB", (40, 20), "gray").save(cwd / "side.png")
        return "done"

    monkeypatch.setattr(stage, "run_codex", codex)
    critics = []

    def critic(kind, checklist, images, *, cwd):
        critics.append(images)
        return Verdict(True, (), "ok")

    monkeypatch.setattr(stage, "run_critic", critic)
    return (
        root,
        plan,
        calls,
        critics,
        Settings(repo, work),
        AssetSpec("e46-body", "base-car", "e46", "e46-coupe"),
    )


def run(setup):
    root, plan, _, _, settings, asset = setup
    (root / "plan.json").write_text(json.dumps(plan))
    return stage.synth(asset, settings)


def test_synth_harvests_and_records_inputs_and_prompt(setup):
    root, _, calls, critics, _, _ = setup
    result = run(setup)
    assert result.ok, result.messages
    assert (root / "views/side.png").is_file()
    assert len(calls) == 1
    assert calls[0][0].endswith("EXTRA")
    assert "left side" in calls[0][0] and "nose points to" in calls[0][0]
    assert calls[0][2] == root
    assert all(path.is_absolute() for path in calls[0][1])
    assert critics[0][-1] == root / "views/side.png"
    assert [path.stem for path in critics[0][:-1]] == ["a", "b"]
    assert load_provenance(root / "provenance.json")[0].inputs == ("a", "b")


def test_synth_skips_existing_view(setup):
    assert run(setup).ok
    assert run(setup).ok
    assert len(setup[2]) == 1


def test_unreviewed_image_is_never_prepared_for_upload(setup, monkeypatch):
    setup[1]["reviewed_inputs"] = []
    monkeypatch.setattr(stage, "prepare_image", lambda *_: pytest.fail("prepared before review"))
    assert not run(setup).ok
    assert not setup[2]


def test_force_drops_approval_and_side_report(setup):
    root = setup[0]
    assert run(setup).ok
    (root / "approved.json").write_text(json.dumps({"views": {"side": "old", "front": "keep"}}))
    (root / "proportion.json").write_text('{"ok":true}')
    setup[1]["force"] = ["side"]
    assert run(setup).ok
    assert json.loads((root / "approved.json").read_text())["views"] == {"front": "keep"}
    assert not (root / "proportion.json").exists()
    assert len(setup[2]) == 2


def test_synth_without_plan_is_clear_not_ok(setup):
    root, _, _, _, settings, asset = setup
    (root / "plan.json").unlink()
    result = stage.synth(asset, settings)
    assert not result.ok and "plan.json" in result.messages[0]


def test_login_refusal_is_not_retried(setup, monkeypatch):
    monkeypatch.setattr(
        stage,
        "run_critic",
        lambda *a, **kw: Verdict(
            False,
            (Issue("blocker", "codex critic failed: codex is not using the ChatGPT login", ""),),
            "",
        ),
    )
    assert not run(setup).ok
    assert len(setup[2]) == 1


def test_fallback_lists_known_views_only(setup):
    setup[1]["fallback"] = ["unknown"]
    assert not run(setup).ok
    assert not setup[2]


def test_fal_refused_when_no_guard_failed(setup):
    assert run(setup).ok
    setup[1]["views"]["side"]["engine"] = "fal"
    setup[1]["fallback"] = ["side"]
    result = run(setup)
    assert not result.ok and "failed critic or proportion" in result.messages[-1]


def test_harvest_last_message_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    path = tmp_path / "output.png"
    Image.new("RGB", (5, 5)).save(path)
    assert stage._harvest(cwd, "side", f"Saved `{path}`", Settings(repo, tmp_path)) == path


def test_fal_fallback_requires_image_edit_registry_entry(setup, monkeypatch):
    assert run(setup).ok
    root = setup[0]
    provenance = json.loads((root / "provenance.json").read_text())
    # Make the cached verdict describe a real failed guard, bound to these bytes.
    provenance[0]["critic_ok"] = False
    (root / "provenance.json").write_text(json.dumps(provenance))
    setup[1]["views"]["side"]["engine"] = "fal"
    setup[1]["fallback"] = ["side"]
    monkeypatch.setattr(stage, "load_generators", lambda *_: {})
    result = run(setup)
    assert not result.ok
    assert "image-edit entry" in result.messages[-1]
    assert len(setup[2]) == 1


def test_prompt_iteration_changes_provenance_hash(setup):
    assert run(setup).ok
    path = setup[0] / "provenance.json"
    first = load_provenance(path)[0].prompt_sha256
    setup[1]["force"] = ["side"]
    setup[1]["views"]["side"]["prompt_extra"] = "--keep the wheelbase longer"
    assert run(setup).ok
    assert load_provenance(path)[0].prompt_sha256 != first
    assert setup[2][-1][0].startswith("Create")


def test_harvest_refuses_repo_image(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    image = repo / "side.png"
    Image.new("RGB", (5, 5)).save(image)
    with pytest.raises(ValueError, match="inside the repo"):
        stage._harvest(cwd, "side", str(image), Settings(repo, tmp_path))


def test_harvest_never_reuses_an_old_png(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    old = cwd / "front.png"
    Image.new("RGB", (5, 5)).save(old)
    with pytest.raises(ValueError, match="expected one generated PNG"):
        stage._harvest(cwd, "side", "done", Settings(repo, tmp_path), old_pngs={old})


def test_unproven_existing_png_is_regenerated(setup):
    target = setup[0] / "views/side.png"
    target.parent.mkdir()
    Image.new("RGB", (5, 5)).save(target)
    assert run(setup).ok
    assert len(setup[2]) == 1


def test_failed_critic_can_be_retried(setup, monkeypatch):
    monkeypatch.setattr(stage, "run_critic", lambda *a, **kw: Verdict(False, (), "crashed"))
    assert not run(setup).ok
    monkeypatch.setattr(stage, "run_critic", lambda *a, **kw: Verdict(True, (), "ok"))
    assert run(setup).ok
    assert len(setup[2]) == 2
