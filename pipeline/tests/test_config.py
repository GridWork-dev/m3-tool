from pathlib import Path

from m3_pipeline.config import load_settings


def test_default_work_dir_is_outside_repo() -> None:
    s = load_settings({})
    assert s.work_dir == Path("~/.cache/m3-tool").expanduser()
    assert not s.work_dir.is_relative_to(s.repo_root)


def test_env_overrides_work_dir(tmp_path: Path) -> None:
    assert load_settings({"M3_WORK_DIR": str(tmp_path)}).work_dir == tmp_path


def test_repo_root_contains_package_json() -> None:
    assert (load_settings({}).repo_root / "package.json").exists()
