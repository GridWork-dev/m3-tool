from pathlib import Path

import pytest

from m3_pipeline.config import Settings
from m3_pipeline.stages.lib.paths import stage_dir, subject_body


def _settings(tmp_path: Path) -> Settings:
    return Settings(repo_root=tmp_path / "repo", work_dir=tmp_path / "work")


def test_stage_dir_is_created_under_assets_id_stage(tmp_path: Path) -> None:
    path = stage_dir(_settings(tmp_path), "e46-coupe-body", "proportion")
    assert path == tmp_path / "work/assets/e46-coupe-body/proportion"
    assert path.is_dir()


def test_stage_dir_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = stage_dir(settings, "e46-coupe-body", "export")
    (first / "kept.txt").write_text("x", "utf-8")
    assert stage_dir(settings, "e46-coupe-body", "export") == first
    assert (first / "kept.txt").read_text("utf-8") == "x"


def test_stage_dir_refuses_a_work_dir_inside_the_repo(tmp_path: Path) -> None:
    settings = Settings(repo_root=tmp_path, work_dir=tmp_path / "work")
    with pytest.raises(ValueError, match="inside the repo"):
        stage_dir(settings, "e46-coupe-body", "export")
    assert not (tmp_path / "work").exists()  # refused before anything was created


def test_stage_dir_refuses_a_work_dir_equal_to_the_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="inside the repo"):
        stage_dir(Settings(repo_root=tmp_path, work_dir=tmp_path), "e46-coupe-body", "export")


def test_stage_dir_refuses_a_repo_reached_through_a_symlink(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "link").symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError, match="inside the repo"):
        stage_dir(Settings(repo_root=repo, work_dir=tmp_path / "link" / "work"), "a", "b")


@pytest.mark.parametrize(
    "asset_id,stage",
    [
        ("..", "export"),
        ("a/b", "export"),
        ("", "export"),
        ("e46", ".."),
        ("e46", "a/b"),
        ("e46", ""),
    ],
)
def test_stage_dir_refuses_a_name_that_could_leave_its_folder(
    tmp_path: Path, asset_id: str, stage: str
) -> None:
    with pytest.raises(ValueError, match="path segment"):
        stage_dir(_settings(tmp_path), asset_id, stage)


@pytest.mark.parametrize(
    "subject,body",
    [("e46-coupe", "coupe"), ("e46-coupe-interior", "coupe"), ("e46-convertible", "convertible")],
)
def test_subject_body_takes_the_body_token_and_strips_interior(subject: str, body: str) -> None:
    assert subject_body(subject) == body


@pytest.mark.parametrize("subject", ["product-x", "E46 Coupe", "e46", "e46-coupe-exterior", ""])
def test_subject_body_rejects_any_other_shape(subject: str) -> None:
    with pytest.raises(ValueError, match="subject"):
        subject_body(subject)
