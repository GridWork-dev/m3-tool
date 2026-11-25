import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from m3_pipeline.config import load_settings
from m3_pipeline.prices.apply import apply_observations
from m3_pipeline.prices.models import Observation
from m3_pipeline.prices.report import CheckReport


def observation(option: str | None = None, amount: str = "110") -> Observation:
    return Observation(
        "fixture-wheel",
        option,
        "https://example.test/p",
        "Fixture Seller",
        Decimal(amount),
        "USD",
        date(2026, 11, 24),
    )


def part_file(tmp_path: Path) -> Path:
    path = tmp_path / "fixture-wheel.yaml"
    path.write_text("""# keep header
id: fixture-wheel
name: Fixture Wheel # keep inline
# keep prices intro
prices:
  - amount: 100
    currency: USD
    seller: Fixture Seller
    checked: 2026-11-23
    url: https://example.test/p
# keep unrelated comment
brand: Fixture Co
options:
  - id: wide
    label: Wide
""")
    return path


def test_apply_preserves_everything_but_prices(tmp_path: Path) -> None:
    path = part_file(tmp_path)
    before: dict[str, Any] = yaml.safe_load(path.read_text())
    result = apply_observations(tmp_path, CheckReport(observations=[observation()]))
    text = path.read_text()
    after: dict[str, Any] = yaml.safe_load(text)
    assert result.changed_files == [path]
    assert list(before) == list(after)
    assert {k: v for k, v in before.items() if k != "prices"} == {
        k: v for k, v in after.items() if k != "prices"
    }
    assert all(
        comment in text
        for comment in (
            "# keep header",
            "# keep inline",
            "# keep prices intro",
            "# keep unrelated comment",
        )
    )
    assert len(after["prices"]) == 2
    assert list(after["prices"][-1]) == ["amount", "currency", "seller", "checked", "url"]


def test_unchanged_within_seven_days_is_not_duplicated(tmp_path: Path) -> None:
    path = part_file(tmp_path)
    original = path.read_bytes()
    result = apply_observations(tmp_path, CheckReport(observations=[observation(amount="100")]))
    assert not result.changed_files and path.read_bytes() == original


def test_apply_writes_option_prices_on_their_options(tmp_path: Path) -> None:
    path = part_file(tmp_path)
    result = apply_observations(tmp_path, CheckReport(observations=[observation("wide")]))
    row: dict[str, Any] = yaml.safe_load(path.read_text())
    assert result.changed_files == [path]
    assert len(row["prices"]) == 1 and row["options"][0]["prices"][0]["amount"] == 110
    assert (
        apply_observations(tmp_path, CheckReport(observations=[observation("wide")])).changed_files
        == []
    )


def test_apply_then_check_data_passes(tmp_path: Path) -> None:
    repo = load_settings().repo_root
    data = tmp_path / "data"
    shutil.copytree(repo / "tests/fixtures/data/valid", data)
    obs = Observation(
        "fixture-wheel",
        "fixture-wheel-17x8",
        "https://example.com/fixture-wheel-17x8",
        "Fixture Seller",
        Decimal("110"),
        "USD",
        date(2026, 11, 24),
    )
    assert apply_observations(data / "parts", CheckReport(observations=[obs])).changed_files
    result = subprocess.run(
        ["node", "tools/check-data.ts", str(data)], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_apply_dry_run_lists_files_without_writing(tmp_path: Path) -> None:
    path = part_file(tmp_path)
    original = path.read_bytes()
    result = apply_observations(tmp_path, CheckReport(observations=[observation()]), dry_run=True)
    assert result.changed_files == [path] and path.read_bytes() == original
