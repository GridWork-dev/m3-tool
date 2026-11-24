import re

from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.config import load_settings


def test_every_command_in_the_runbook_exists() -> None:
    text = (load_settings().repo_root / "docs/runbooks/refs-collection.md").read_text()
    cmds = re.findall(r"^uv run pipeline (refs(?: [a-z]+){1,2})", text, re.M)
    assert cmds and all(
        CliRunner().invoke(app, [*c.split(), "--help"]).exit_code == 0 for c in cmds
    )


def test_runbook_states_the_hard_rules_and_the_blocked_site_fallback() -> None:
    t = (load_settings().repo_root / "docs/runbooks/refs-collection.md").read_text().lower()
    assert all(
        s in t
        for s in (
            "robots.txt",
            "captcha",
            "proxy",
            "user-agent",
            "never commit",
            "m3-tool-refs",
            "unknown",
            "normal browser",
            "refs import",
            "e46/2s",
            "drive_side",
        )
    )
