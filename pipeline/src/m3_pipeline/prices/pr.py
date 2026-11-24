import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path

from m3_pipeline.config import load_settings
from m3_pipeline.prices.apply import ApplyResult
from m3_pipeline.prices.report import CheckReport

_run = subprocess.run


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def change_table(apply_result: ApplyResult, report: CheckReport) -> str:
    lines = ["| Part / option | Seller | Price (old → new) | Review |", "| --- | --- | --- | --- |"]
    for change in apply_result.changes:
        obs, old = change.observation, change.before
        flags: list[str] = []
        if old and old > 0:
            ratio = max(obs.amount / old, old / obs.amount)
            if abs(obs.amount - old) / old > Decimal("0.2"):
                flags.append(">20%")
            if ratio > 10:
                flags.append(">10×")
        label = obs.part_id + (f" / {obs.option_id}" if obs.option_id else "")
        lines.append(
            f"| {_cell(label)} | {_cell(obs.seller)} | "
            f"{old if old is not None else '—'} → {obs.amount} {obs.currency} | "
            f"{', '.join(flags)} |"
        )
    if report.flagged:
        lines.extend(["", "Flagged for review:", *("- " + _cell(f) for f in report.flagged)])
    return "\n".join([*lines, "", report.render()])


def open_pr(
    *,
    apply_result: ApplyResult,
    report: CheckReport,
    today: date,
    base: str = "main",
    runner_env: Mapping[str, str],
) -> str | None:
    if not apply_result.changed_files or apply_result.dry_run:
        return None
    settings = load_settings()
    root = settings.repo_root.resolve()
    paths: list[str] = []
    for path in apply_result.changed_files:
        resolved = path.resolve()
        if not resolved.is_relative_to(root / "data/parts") or resolved.suffix not in {
            ".yaml",
            ".yml",
        }:
            raise ValueError("prices PR may stage only YAML under data/parts")
        paths.append(resolved.relative_to(root).as_posix())

    def command(args: list[str]) -> str:
        result = _run(args, cwd=root, env=dict(runner_env), capture_output=True, text=True)
        if result.returncode:
            # Vendor/git output can echo credentials; the command and exit code suffice.
            raise RuntimeError(f"{args[0]} failed (exit {result.returncode})")
        return result.stdout.strip()

    for args in (
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--cached", "--name-only", "-z"],
    ):
        dirty = set(command(args).split("\0")) - {""}
        if dirty - set(paths):
            raise ValueError("unrelated tracked changes must be committed before prices pr")
    branch = f"data/prices-{today.isoformat()}"
    command(["git", "switch", "-c", branch])
    command(["git", "add", "--", *paths])
    command(["git", "commit", "-m", f"data(prices): update weekly observations {today}"])
    if runner_env.get("M3_PRICES_NO_PR") == "1":
        return None
    command(["git", "push", "-u", "origin", branch])
    directory = settings.work_dir / "prices"
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=directory, suffix=".md")
    try:
        with os.fdopen(fd, "w") as body:
            body.write(f"Weekly price observations checked {today}.\n\n")
            body.write(change_table(apply_result, report))
        url = command(
            [
                "gh",
                "pr",
                "create",
                "--base",
                base,
                "--head",
                branch,
                "--title",
                f"data(prices): weekly observations {today}",
                "--body-file",
                name,
            ]
        )
    finally:
        Path(name).unlink(missing_ok=True)
    if not re.fullmatch(r"https://github\.com/[^/\s]+/[^/\s]+/pull/[0-9]+", url):
        raise RuntimeError("gh pr create returned no pull request URL")
    return url
