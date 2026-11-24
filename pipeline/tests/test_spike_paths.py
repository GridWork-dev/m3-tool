from pathlib import Path

import pytest

from m3_pipeline.config import Settings
from m3_pipeline.stages.lib.paths import require_outside_repo, stage_dir, subject_body


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


def _is_case_insensitive(directory: Path) -> bool:
    (directory / "CaseProbe").mkdir()
    return (directory / "caseprobe").exists()


def test_stage_dir_refuses_a_work_dir_inside_the_repo_spelled_in_another_case(
    tmp_path: Path,
) -> None:
    # macOS volumes ignore case, so `/Users/x/Repo` and `/users/x/repo` are one folder, and
    # resolve() does not canonicalize the spelling.
    if not _is_case_insensitive(tmp_path):
        pytest.skip("case-sensitive filesystem: an odd-cased path names a different folder")
    repo = tmp_path / "Repo"
    repo.mkdir()
    settings = Settings(repo_root=repo, work_dir=tmp_path / "rEPO" / "work")
    with pytest.raises(ValueError, match="inside the repo"):
        stage_dir(settings, "e46-coupe-body", "export")
    assert list(repo.iterdir()) == []


def test_stage_dir_refuses_a_repo_spelled_in_another_case_than_the_work_dir(
    tmp_path: Path,
) -> None:
    if not _is_case_insensitive(tmp_path):
        pytest.skip("case-sensitive filesystem: an odd-cased path names a different folder")
    repo = tmp_path / "Repo"
    (repo / "work").mkdir(parents=True)
    settings = Settings(repo_root=tmp_path / "rEPO", work_dir=repo / "work")
    with pytest.raises(ValueError, match="inside the repo"):
        stage_dir(settings, "e46-coupe-body", "export")


def _link_into_repo(tmp_path: Path, where: str, target: str) -> tuple[Settings, Path]:
    """A work dir outside the repo whose child `where` is a symlink to `repo/<target>`."""
    repo = tmp_path / "repo"
    (repo / "inside").mkdir(parents=True)
    work = tmp_path / "work"
    link = work / where
    link.parent.mkdir(parents=True)
    link.symlink_to(repo / target, target_is_directory=True)
    return Settings(repo_root=repo, work_dir=work), repo


@pytest.mark.parametrize(
    "where",
    ["assets", "assets/e46-coupe-body", "assets/e46-coupe-body/export"],
)
@pytest.mark.parametrize("target", ["inside", "not-yet"])
def test_stage_dir_refuses_a_child_folder_that_is_a_symlink_into_the_repo(
    tmp_path: Path, where: str, target: str
) -> None:
    # The work dir itself is outside the repo, so only the destination's real location shows
    # the escape. `not-yet` is a dangling link: creating the stage dir would create it in the repo.
    settings, repo = _link_into_repo(tmp_path, where, target)
    before = sorted(p.name for p in repo.iterdir())
    with pytest.raises(ValueError, match="inside the repo"):
        stage_dir(settings, "e46-coupe-body", "export")
    assert sorted(p.name for p in repo.iterdir()) == before
    assert list((repo / "inside").iterdir()) == []


def test_stage_dir_accepts_a_child_symlink_that_stays_outside_the_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "bigdisk"
    elsewhere.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (work / "assets").symlink_to(elsewhere, target_is_directory=True)
    path = stage_dir(Settings(repo_root=repo, work_dir=work), "e46-coupe-body", "export")
    assert path.resolve() == (elsewhere / "e46-coupe-body" / "export").resolve()
    assert path.is_dir()


def test_require_outside_repo_names_where_the_path_really_points(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "out").symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError, match="inside the repo") as info:
        require_outside_repo(repo, tmp_path / "out" / "refs" / "images")
    assert str(repo.resolve() / "refs" / "images") in str(info.value)
    require_outside_repo(repo, tmp_path / "elsewhere" / "refs")


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
