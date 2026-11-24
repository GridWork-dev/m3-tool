import ast
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

import m3_pipeline.stages.validate as validate_mod
from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings, load_settings
from m3_pipeline.stages import REGISTRY, StageResult
from m3_pipeline.stages.validate import validate

ASSET = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")
REPO = load_settings({}).repo_root


def _export_path(work_dir: Path) -> Path:
    return work_dir / "assets/e46-coupe-body/export/e46-coupe-body.glb"


def _export(work_dir: Path) -> Path:
    glb = _export_path(work_dir)
    glb.parent.mkdir(parents=True)
    glb.write_bytes(b"x")
    return glb


def _report_path(work_dir: Path) -> Path:
    return work_dir / "assets/e46-coupe-body/export/e46-coupe-body.validate.json"


STATS = {"triangles": 120000, "bytes": 5242880}


def _stub_validator(
    monkeypatch: pytest.MonkeyPatch, code: int, stdout: str, stderr: str = ""
) -> list[list[str]]:
    """Replace the node call with a canned result, and return the commands it was given."""
    calls: list[list[str]] = []

    def fake(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout, stderr)

    monkeypatch.setattr(validate_mod, "_run", fake)
    return calls


def test_missing_export_fails_with_hint(tmp_path: Path) -> None:
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and "run --stage export first" in r.messages[0]


def test_passes_kind_and_maps_issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _export(tmp_path)
    calls: list[list[str]] = []

    def fake(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            1,
            json.dumps(
                {
                    "ok": False,
                    "issues": [{"code": "units", "severity": "error", "message": "Z length 449 m"}],
                }
            ),
            "",
        )

    monkeypatch.setattr(validate_mod, "_run", fake)
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.messages == ["ERROR units: Z length 449 m"]
    assert calls[0][-3:] == ["--kind", "base-car", "--json"]


def test_validate_is_registered() -> None:
    assert "validate" in REGISTRY


def test_runs_the_repo_validator_on_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    glb = _export(tmp_path)
    calls = _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": []}))
    validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert calls == [
        ["node", str(REPO / "tools/validate-asset.ts"), str(glb), "--kind", "base-car", "--json"]
    ]


def test_passes_when_the_report_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _export(tmp_path)
    _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": []}))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert r.ok and r.outputs == [_report_path(tmp_path)]
    assert r.messages == ["e46-coupe-body.glb meets the base-car contract"]


def test_writes_the_cli_report_next_to_the_export_and_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    report: dict[str, object] = {"ok": True, "issues": [], "stats": STATS}
    _stub_validator(monkeypatch, 0, json.dumps(report))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    path = _report_path(tmp_path)
    assert r.ok and r.outputs == [path]
    assert path.parent == tmp_path / "assets/e46-coupe-body/export"
    assert json.loads(path.read_text(encoding="utf-8")) == report  # including the stats
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_the_report_is_the_cli_json_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    stdout = '{"ok":true,"issues":[],"stats":{"triangles":1200,"bytes":4096}}\n'
    _stub_validator(monkeypatch, 0, stdout)
    validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert _report_path(tmp_path).read_text(encoding="utf-8") == stdout


def test_a_failing_report_is_written_and_listed_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    report = {
        "ok": False,
        "issues": [{"code": "units", "severity": "error", "message": "Z length 449 m"}],
        "stats": {"triangles": 120000, "bytes": 5242880},
    }
    _stub_validator(monkeypatch, 1, json.dumps(report))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.outputs == [_report_path(tmp_path)]
    assert json.loads(_report_path(tmp_path).read_text(encoding="utf-8")) == report


def test_a_second_run_replaces_the_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _export(tmp_path)
    _stub_validator(monkeypatch, 1, json.dumps({"ok": False, "issues": []}))
    validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": [], "stats": STATS}))
    validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert json.loads(_report_path(tmp_path).read_text(encoding="utf-8"))["ok"] is True


def test_no_report_file_is_written_when_the_validator_gave_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    _stub_validator(monkeypatch, 2, "not json", "usage: --kind is required")
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.outputs == []
    assert not _report_path(tmp_path).exists()


def test_a_report_that_cannot_be_written_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": []}))

    def refuse(self: Path, *args: object, **kwargs: object) -> int:
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "write_text", refuse)
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.outputs == []
    assert "could not write" in r.messages[0] and "e46-coupe-body.validate.json" in r.messages[0]


def _stale_report(work_dir: Path) -> Path:
    """An old report next to an export, as a previous successful run leaves it."""
    path = _report_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ok":true,"issues":[],"stats":{"triangles":120000,"bytes":1}}\n', "utf-8")
    return path


def test_a_stale_report_is_removed_when_the_export_is_missing(tmp_path: Path) -> None:
    stale = _stale_report(tmp_path)
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.outputs == []
    assert not stale.exists()


def test_a_stale_report_is_removed_when_the_validator_gives_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    stale = _stale_report(tmp_path)
    _stub_validator(monkeypatch, 2, "not json", "boom")
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.outputs == []
    assert not stale.exists()


def test_a_stale_report_is_removed_when_node_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    stale = _stale_report(tmp_path)

    def fake(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("node")

    monkeypatch.setattr(validate_mod, "_run", fake)
    assert not validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path)).ok
    assert not stale.exists()


def test_a_stale_report_never_survives_a_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    _stale_report(tmp_path)
    _stub_validator(monkeypatch, 1, json.dumps({"ok": False, "issues": [], "stats": STATS}))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert r.outputs == [_report_path(tmp_path)]
    assert json.loads(_report_path(tmp_path).read_text(encoding="utf-8"))["ok"] is False


def test_a_stale_report_that_cannot_be_removed_fails_cleanly(tmp_path: Path) -> None:
    _report_path(tmp_path).mkdir(parents=True)  # a directory where the file goes, so unlink fails
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and r.outputs == []
    assert "could not remove" in r.messages[0] and "e46-coupe-body.validate.json" in r.messages[0]


def test_the_stage_result_type_is_unchanged() -> None:
    # Plan 0B relies on StageResult(ok, messages, outputs) and nothing else.
    assert [f.name for f in dataclasses.fields(StageResult)] == ["ok", "messages", "outputs"]


def test_warnings_do_not_fail_the_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _export(tmp_path)
    warning = {"code": "triangles", "severity": "warning", "message": "1 line primitive skipped"}
    _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": [warning]}))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert r.ok and r.messages[0] == "WARNING triangles: 1 line primitive skipped"


def test_a_failing_exit_code_fails_even_if_the_report_says_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    _stub_validator(monkeypatch, 1, json.dumps({"ok": True, "issues": []}))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok
    assert r.messages == ["validate-asset exited 1 although its report says ok"]


def test_a_failing_exit_code_adds_its_message_after_the_issue_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _export(tmp_path)
    warning = {"code": "triangles", "severity": "warning", "message": "1 line primitive skipped"}
    _stub_validator(monkeypatch, 3, json.dumps({"ok": True, "issues": [warning]}))
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok
    assert r.messages == [
        "WARNING triangles: 1 line primitive skipped",
        "validate-asset exited 3 although its report says ok",
    ]


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json",
        "[]",
        '{"ok": true}',
        '{"ok": 1, "issues": []}',
        '{"ok": true, "issues": [1]}',
    ],
)
def test_a_missing_or_malformed_report_fails_with_the_validators_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    _export(tmp_path)
    _stub_validator(monkeypatch, 2, stdout, "usage: --kind is required")
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok
    assert "exited 2" in r.messages[0] and "usage: --kind is required" in r.messages[0]


def test_node_missing_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _export(tmp_path)

    def fake(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("node")

    monkeypatch.setattr(validate_mod, "_run", fake)
    r = validate(ASSET, Settings(repo_root=REPO, work_dir=tmp_path))
    assert not r.ok and "node" in r.messages[0]


def test_stages_register_when_the_package_is_imported_fresh() -> None:
    # A new interpreter proves registration needs no other import, and that importing the stage
    # module first does not trip over the package importing it back.
    for first in ("m3_pipeline.stages", "m3_pipeline.stages.validate", "m3_pipeline.cli"):
        code = f"import {first}; from m3_pipeline.stages import REGISTRY; print(sorted(REGISTRY))"
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        # Membership, not equality: later plans register more stages.
        registered = ast.literal_eval(out.stdout.strip())
        assert isinstance(registered, list) and "validate" in registered


# ---------------------------------------------------------------------------------------------
# The export folder stays out of the repo (Task 0 ledger N4): the stage reads the GLB and
# writes a report there, and refuses both when the folder resolves into the repo.
# ---------------------------------------------------------------------------------------------


def test_refuses_an_export_folder_inside_the_repo_for_both_the_read_and_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=repo / "work")
    glb = _export(settings.work_dir)  # the GLB exists, so only the guard can stop the read
    stale = _stale_report(settings.work_dir)
    calls = _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": []}))
    r = validate(ASSET, settings)
    assert not r.ok and r.outputs == []
    assert "inside the repo" in r.messages[0]
    assert calls == []  # node never read the GLB in the repo
    assert stale.exists() and glb.read_bytes() == b"x"  # and nothing in the repo was touched


def test_refuses_a_glb_that_is_a_link_into_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    target = repo / "elsewhere.glb"
    target.write_bytes(b"repo file")
    link = _export_path(settings.work_dir)
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    calls = _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": []}))
    r = validate(ASSET, settings)
    assert not r.ok and "inside the repo" in r.messages[0]
    assert calls == []
    assert not _report_path(settings.work_dir).exists()


def test_refuses_a_report_that_is_a_link_into_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "work")
    _export(settings.work_dir)
    target = repo / "report.json"
    target.write_text("repo file", "utf-8")
    _report_path(settings.work_dir).symlink_to(target)
    calls = _stub_validator(monkeypatch, 0, json.dumps({"ok": True, "issues": []}))
    r = validate(ASSET, settings)
    assert not r.ok and "inside the repo" in r.messages[0]
    assert calls == []
    assert target.read_text("utf-8") == "repo file"
    assert _report_path(settings.work_dir).is_symlink()  # the link was not followed or replaced
