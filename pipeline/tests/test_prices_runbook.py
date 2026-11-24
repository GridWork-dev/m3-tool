import json
import re
from pathlib import Path

import yaml
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.config import load_settings


def test_every_command_in_the_runbook_exists() -> None:
    root = load_settings().repo_root
    text = (root / "docs/runbooks/weekly-scrape.md").read_text()
    commands = re.findall(
        r"^uv run --project pipeline pipeline (prices(?: [a-z]+){1,2})", text, re.M
    )
    assert commands
    assert {c.split()[1] for c in commands} == {"check", "apply", "pr", "discover", "week"}
    for command in commands:
        result = CliRunner().invoke(app, [*command.split(), "--help"])
        assert result.exit_code == 0, result.output
    package = json.loads((root / "package.json").read_text())
    assert package["scripts"]["scrape:week"] == "uv run --project pipeline pipeline prices week"


def test_runbook_states_the_posture_and_ledger_rules() -> None:
    text = (load_settings().repo_root / "docs/runbooks/weekly-scrape.md").read_text()
    assert all(
        token in text
        for token in ("ADR 0014", "polite", "unblock", "robots", "spend", "one request per product")
    )
    assert all(
        token in text
        for token in ("M3_SPEND_SESSION", "session:<label>", "spike:", "positive", "same-day")
    )


def test_weekly_skill_has_valid_frontmatter_and_links_to_runbook() -> None:
    root = load_settings().repo_root
    skill = root / ".claude/skills/m3-weekly-scrape/SKILL.md"
    text = skill.read_text()
    front: dict[str, str] = yaml.safe_load(text.split("---", 2)[1])
    assert front["name"] == "m3-weekly-scrape" and front["description"]
    target = re.search(r"\]\(([^)]+weekly-scrape\.md)\)", text)
    assert target and (skill.parent / Path(target[1])).resolve().is_file()
