from pathlib import Path

import pytest

from m3_pipeline.config import load_settings


def test_default_work_dir_is_outside_repo() -> None:
    s = load_settings({})
    # Resolved, because ~/.cache can be a symlink on some machines.
    assert s.work_dir == Path("~/.cache/m3-tool").expanduser().resolve()
    assert not s.work_dir.is_relative_to(s.repo_root)


def test_env_overrides_work_dir(tmp_path: Path) -> None:
    assert load_settings({"M3_WORK_DIR": str(tmp_path)}).work_dir == tmp_path


def test_repo_root_contains_package_json() -> None:
    assert (load_settings({}).repo_root / "package.json").exists()


def test_a_relative_work_dir_resolves_against_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    s = load_settings({"M3_WORK_DIR": ".m3-work"})
    assert s.work_dir.is_absolute()
    assert s.work_dir == tmp_path.resolve() / ".m3-work"


def test_a_relative_work_dir_inside_the_repo_is_seen_as_inside_the_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Plan 0B refuses a work dir under the repo. A relative `.m3-work` run from the repo must not
    # slip past that check just because it is not absolute.
    repo_root = load_settings({}).repo_root
    monkeypatch.chdir(repo_root)
    s = load_settings({"M3_WORK_DIR": ".m3-work"})
    assert s.work_dir.is_relative_to(s.repo_root)


def test_a_dotdot_work_dir_is_normalised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    s = load_settings({"M3_REPO_ROOT": str(repo), "M3_WORK_DIR": "repo/sub/../.m3-work"})
    assert s.work_dir == repo.resolve() / ".m3-work"
    assert s.work_dir.is_relative_to(s.repo_root)


def test_a_symlinked_work_dir_resolves_to_the_real_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    s = load_settings({"M3_REPO_ROOT": str(repo), "M3_WORK_DIR": str(link / ".m3-work")})
    assert s.work_dir.is_relative_to(s.repo_root)


def test_a_relative_repo_root_is_resolved_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_settings({"M3_REPO_ROOT": "."}).repo_root == tmp_path.resolve()


def test_home_is_still_expanded_in_both_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/nonexistent-home")
    s = load_settings({"M3_REPO_ROOT": "~/repo", "M3_WORK_DIR": "~/work"})
    assert s.repo_root == Path("/nonexistent-home/repo")
    assert s.work_dir == Path("/nonexistent-home/work")
