import json
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

import m3_pipeline.stages.export as export_mod
import m3_pipeline.stages.validate as validate_mod
from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings, load_settings
from m3_pipeline.stages import REGISTRY
from m3_pipeline.stages.export import export
from m3_pipeline.stages.validate import validate

CAR = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")
INTERIOR = AssetSpec("e46-coupe-interior", "interior", "e46", "e46-coupe-interior")
REPO = load_settings({}).repo_root


class FakeNode:
    """Stands in for `node tools/export-glb.ts`: records each call and writes the two outputs.

    The markers file is read while the call runs, because the stage removes it afterwards.
    """

    def __init__(self, code: int = 0, stdout: str = "", stderr: str = "", write: bool = True):
        self.code, self.stdout, self.stderr, self.write = code, stdout, stderr, write
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, object]] = []
        self.markers: list[object] = []

    def __call__(self, cmd: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        args = list(cmd)
        self.calls.append(args)
        self.kwargs.append(kwargs)
        if "--markers" in args:
            path = Path(args[args.index("--markers") + 1])
            self.markers.append(json.loads(path.read_text("utf-8")))
        if self.code == 0 and self.write:
            glb = Path(args[3])
            glb.write_bytes(b"glb")
            glb.with_name(glb.name.removesuffix(".glb") + ".proxy.json").write_text("{}", "utf-8")
        return subprocess.CompletedProcess(args, self.code, self.stdout, self.stderr)


def _install(monkeypatch: pytest.MonkeyPatch, node: FakeNode) -> FakeNode:
    monkeypatch.setattr(export_mod, "_run", node)
    return node


def _settings(work_dir: Path) -> Settings:
    return Settings(repo_root=REPO, work_dir=work_dir)


def _stage(work_dir: Path, asset: AssetSpec, stage: str) -> Path:
    return work_dir / "assets" / asset.id / stage


def _cleaned(work_dir: Path, asset: AssetSpec = CAR) -> Path:
    glb = _stage(work_dir, asset, "cleanup") / f"{asset.id}.cleaned.glb"
    glb.parent.mkdir(parents=True, exist_ok=True)
    glb.write_bytes(b"cleaned")
    return glb


def _sidecar(work_dir: Path, asset: AssetSpec, payload: object) -> Path:
    path = _stage(work_dir, asset, "cleanup") / f"{asset.id}.cleaned.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), "utf-8")
    return path


def _out(work_dir: Path, asset: AssetSpec = CAR) -> Path:
    return _stage(work_dir, asset, "export") / f"{asset.id}.glb"


def _proxy(work_dir: Path, asset: AssetSpec = CAR) -> Path:
    return _stage(work_dir, asset, "export") / f"{asset.id}.proxy.json"


def test_export_is_registered() -> None:
    assert "export" in REGISTRY


def test_export_stage_runs_node_with_kind_and_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleaned = _cleaned(tmp_path)
    _sidecar(
        tmp_path,
        CAR,
        {"candidate": "call-1", "method": "tripo", "markers": {"generator": "tripo", "v": 2}},
    )
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, _settings(tmp_path))
    assert result.ok, result.messages
    [argv] = node.calls
    assert argv[:7] == [
        "node",
        str(REPO / "tools/export-glb.ts"),
        str(cleaned),
        str(_out(tmp_path)),
        "--kind",
        "base-car",
        "--markers",
    ]
    assert len(argv) == 8
    assert node.markers == [{"generator": "tripo", "v": 2}]


def test_export_stage_removes_its_temporary_markers_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    _sidecar(tmp_path, CAR, {"candidate": "c", "method": "tripo", "markers": {"a": 1}})
    node = _install(monkeypatch, FakeNode())
    export(CAR, _settings(tmp_path))
    markers_file = Path(node.calls[0][-1])
    assert not markers_file.exists()


def test_export_stage_without_a_sidecar_passes_no_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, _settings(tmp_path))
    assert result.ok, result.messages
    assert "--markers" not in node.calls[0]
    assert node.markers == []


def test_export_stage_passes_the_per_part_markers_of_an_interior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path, INTERIOR)
    _sidecar(
        tmp_path,
        INTERIOR,
        {
            "parts": {
                "dash": {"candidate": "call-1", "markers": {"generator": "tripo"}},
                "seat_driver": {"candidate": "call-2", "markers": {"generator": "hunyuan"}},
            }
        },
    )
    node = _install(monkeypatch, FakeNode())
    result = export(INTERIOR, _settings(tmp_path))
    assert result.ok, result.messages
    assert node.calls[0][4:6] == ["--kind", "interior"]
    assert node.markers == [
        {"dash": {"generator": "tripo"}, "seat_driver": {"generator": "hunyuan"}}
    ]


def test_export_stage_needs_the_cleaned_glb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, _settings(tmp_path))
    assert not result.ok and result.outputs == []
    assert "run --stage cleanup first" in result.messages[0]
    assert "e46-coupe-body.cleaned.glb" in result.messages[0]
    assert node.calls == []


def test_export_stage_writes_to_the_path_validate_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    exporting = _install(monkeypatch, FakeNode())
    assert export(CAR, _settings(tmp_path)).ok

    validating: list[list[str]] = []

    def fake_validator(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        validating.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"ok": True, "issues": []}), "")

    monkeypatch.setattr(validate_mod, "_run", fake_validator)
    assert validate(CAR, _settings(tmp_path)).ok
    assert exporting.calls[0][3] == validating[0][2] == str(_out(tmp_path))


def test_export_stage_lists_the_proxy_json_in_its_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    _install(monkeypatch, FakeNode(stdout="wrote it"))
    result = export(CAR, _settings(tmp_path))
    assert result.ok
    assert result.outputs == [_out(tmp_path), _proxy(tmp_path)]
    assert all(path.is_file() for path in result.outputs)
    assert _proxy(tmp_path).name == "e46-coupe-body.proxy.json"


def test_export_stage_is_not_ok_when_node_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    _install(monkeypatch, FakeNode(code=1, stderr="Error: not a GLB"))
    result = export(CAR, _settings(tmp_path))
    assert not result.ok and result.outputs == []
    assert "exited 1" in result.messages[0] and "Error: not a GLB" in result.messages[0]


def test_export_stage_is_not_ok_when_node_cannot_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)

    def missing(cmd: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("node")

    monkeypatch.setattr(export_mod, "_run", missing)
    result = export(CAR, _settings(tmp_path))
    assert not result.ok and "could not run node" in result.messages[0]


def test_export_stage_is_not_ok_when_node_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)

    def hang(cmd: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(list(cmd), 5)

    monkeypatch.setattr(export_mod, "_run", hang)
    result = export(CAR, _settings(tmp_path))
    assert not result.ok and "timed out" in result.messages[0]


def test_export_stage_gives_node_a_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cleaned(tmp_path)
    node = _install(monkeypatch, FakeNode())
    export(CAR, _settings(tmp_path))
    timeout = node.kwargs[0]["timeout_s"]
    assert isinstance(timeout, int) and 0 < timeout <= 3600


def test_export_stage_is_not_ok_when_node_leaves_no_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    _install(monkeypatch, FakeNode(write=False))
    result = export(CAR, _settings(tmp_path))
    assert not result.ok and result.outputs == []
    assert "did not write" in result.messages[0]


def _old_outputs(work_dir: Path) -> tuple[Path, Path]:
    glb, proxy = _out(work_dir), _proxy(work_dir)
    glb.parent.mkdir(parents=True, exist_ok=True)
    glb.write_bytes(b"old export")
    proxy.write_text('{"sha256": "old"}', "utf-8")
    return glb, proxy


def test_a_failed_export_leaves_no_earlier_glb_or_proxy_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # validate would otherwise bless an export from before the failure.
    _cleaned(tmp_path)
    glb, proxy = _old_outputs(tmp_path)
    _install(monkeypatch, FakeNode(code=1, stderr="boom"))
    assert not export(CAR, _settings(tmp_path)).ok
    assert not glb.exists() and not proxy.exists()


def test_a_missing_cleaned_glb_leaves_no_earlier_glb_or_proxy_behind(tmp_path: Path) -> None:
    glb, proxy = _old_outputs(tmp_path)
    assert not export(CAR, _settings(tmp_path)).ok
    assert not glb.exists() and not proxy.exists()


@pytest.mark.parametrize(
    ("asset", "payload"),
    [
        (CAR, "not json"),
        (CAR, []),
        (CAR, {"candidate": "c", "method": "tripo"}),
        (CAR, {"markers": ["a"]}),
        (INTERIOR, {"candidate": "c", "markers": {}}),
        (INTERIOR, {"parts": []}),
        (INTERIOR, {"parts": {"dash": {"candidate": "c"}}}),
        (INTERIOR, {"parts": {"dash": {"markers": "x"}}}),
        (INTERIOR, {"parts": {"dash": 1}}),
    ],
)
def test_a_sidecar_of_the_wrong_shape_fails_instead_of_dropping_the_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asset: AssetSpec, payload: object
) -> None:
    _cleaned(tmp_path, asset)
    sidecar = _sidecar(tmp_path, asset, payload)
    node = _install(monkeypatch, FakeNode())
    result = export(asset, _settings(tmp_path))
    assert not result.ok and result.outputs == []
    assert sidecar.name in result.messages[0]
    assert node.calls == []


# ---------------------------------------------------------------------------------------------
# The destination stays out of the repo (Task 0 ledger N4)
# ---------------------------------------------------------------------------------------------


def _inside_a_fake_repo(tmp_path: Path) -> Settings:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Settings(repo_root=repo, work_dir=repo / "work")


def test_export_refuses_a_work_dir_inside_the_repo_for_both_the_read_and_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _inside_a_fake_repo(tmp_path)
    cleaned = _cleaned(settings.work_dir)  # the file to read exists, so only the guard stops it
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, settings)
    assert not result.ok and result.outputs == []
    assert "inside the repo" in result.messages[0]
    assert node.calls == []  # nothing was read from the repo or written into it
    assert cleaned.read_bytes() == b"cleaned"
    assert not _stage(settings.work_dir, CAR, "export").exists()


def test_export_refuses_a_glb_that_is_a_link_into_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    _cleaned(settings.work_dir)
    target = repo / "elsewhere.glb"
    target.write_bytes(b"repo file")
    out = _out(settings.work_dir)
    out.parent.mkdir(parents=True)
    out.symlink_to(target)
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, settings)
    assert not result.ok and "inside the repo" in result.messages[0]
    assert node.calls == []
    assert target.read_bytes() == b"repo file"


def test_export_refuses_a_cleaned_glb_that_is_a_link_into_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    target = repo / "elsewhere.glb"
    target.write_bytes(b"repo file")
    cleaned = _stage(settings.work_dir, CAR, "cleanup") / f"{CAR.id}.cleaned.glb"
    cleaned.parent.mkdir(parents=True)
    cleaned.symlink_to(target)
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, settings)
    assert not result.ok and "inside the repo" in result.messages[0]
    assert node.calls == []


def test_export_refuses_to_write_the_markers_file_inside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "tmp").mkdir(parents=True)
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    _cleaned(settings.work_dir)
    _sidecar(settings.work_dir, CAR, {"markers": {"a": 1}})
    monkeypatch.setattr(tempfile, "tempdir", str(repo / "tmp"))  # as if TMPDIR pointed there
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, settings)
    assert not result.ok and "inside the repo" in result.messages[0]
    assert node.calls == []
    assert list((repo / "tmp").iterdir()) == []  # the temporary folder is gone, nothing left


def _stale_validate_report(work_dir: Path) -> Path:
    """The report an earlier `validate` run left next to an earlier export."""
    path = _stage(work_dir, CAR, "export") / "e46-coupe-body.validate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ok":true,"issues":[],"stats":{"triangles":120000,"bytes":1}}\n', "utf-8")
    return path


def test_a_new_export_removes_the_validate_report_of_the_old_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    stale = _stale_validate_report(tmp_path)
    _install(monkeypatch, FakeNode())
    result = export(CAR, _settings(tmp_path))
    assert result.ok
    assert not stale.exists()
    assert result.outputs == [_out(tmp_path), _proxy(tmp_path)]  # the report is not an output


def test_a_failed_export_leaves_no_validate_report_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cleaned(tmp_path)
    stale = _stale_validate_report(tmp_path)
    _install(monkeypatch, FakeNode(code=1, stderr="boom"))
    assert not export(CAR, _settings(tmp_path)).ok
    assert not stale.exists()


def test_a_missing_cleaned_glb_leaves_no_validate_report_behind(tmp_path: Path) -> None:
    stale = _stale_validate_report(tmp_path)
    assert not export(CAR, _settings(tmp_path)).ok
    assert not stale.exists()


def test_the_validate_report_that_is_a_link_into_the_repo_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    _cleaned(settings.work_dir)
    target = repo / "report.json"
    target.write_text("repo file", "utf-8")
    report = _stage(settings.work_dir, CAR, "export") / "e46-coupe-body.validate.json"
    report.parent.mkdir(parents=True)
    report.symlink_to(target)
    node = _install(monkeypatch, FakeNode())
    result = export(CAR, settings)
    assert not result.ok and "inside the repo" in result.messages[0]
    assert node.calls == []
    assert target.read_text("utf-8") == "repo file" and report.is_symlink()
