import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

import m3_pipeline.stages.validate as validate_mod
from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings, load_settings
from m3_pipeline.stages import REGISTRY
from m3_pipeline.stages.validate import validate

ASSET = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")
REPO = load_settings({}).repo_root


def _export(work_dir: Path) -> Path:
    glb = work_dir / "assets/e46-coupe-body/export/e46-coupe-body.glb"
    glb.parent.mkdir(parents=True)
    glb.write_bytes(b"x")
    return glb


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
    assert r.ok and r.outputs == []
    assert r.messages == ["e46-coupe-body.glb meets the base-car contract"]


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
