"""The `validate` stage: check an exported GLB against the 3D asset contract.

The contract lives in TypeScript (`src/lib/asset-contract.ts`), so this stage shells out to
`tools/validate-asset.ts` and maps its JSON report to messages. It also saves that report, with
its `stats` (triangle count and size), as `<export>/<id>.validate.json`.
"""

import json
import subprocess
from collections.abc import Callable
from typing import cast

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import StageResult, register


def _run_process(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# Tests replace this to avoid starting node.
_run: Callable[[list[str]], subprocess.CompletedProcess[str]] = _run_process


@register("validate")
def validate(asset: AssetSpec, settings: Settings) -> StageResult:
    glb = settings.work_dir / "assets" / asset.id / "export" / f"{asset.id}.glb"
    if not glb.is_file():
        return StageResult(False, [f"{glb} does not exist; run --stage export first"], [])

    script = settings.repo_root / "tools" / "validate-asset.ts"
    cmd = ["node", str(script), str(glb), "--kind", asset.kind, "--json"]
    try:
        proc = _run(cmd)
    except OSError as error:
        return StageResult(False, [f"could not run node: {error}"], [])

    issues = _parse_issues(proc.stdout)
    if issues is None:
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        message = f"validate-asset exited {proc.returncode} without a report: {detail}"
        return StageResult(False, [message], [])
    messages, ok = issues
    # Keep the CLI's JSON, stats included, next to the export, so later stages (publish) can read
    # the triangle count and size that validation measured instead of measuring again.
    report = glb.with_name(f"{asset.id}.validate.json")
    try:
        report.write_text(
            proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n", "utf-8"
        )
    except OSError as error:
        return StageResult(False, [f"could not write {report}: {error}"], [])
    if proc.returncode != 0:
        if ok:
            messages.append(f"validate-asset exited {proc.returncode} although its report says ok")
        ok = False
    if ok:
        messages.append(f"{glb.name} meets the {asset.kind} contract")
    return StageResult(ok, messages, [report])


def _parse_issues(stdout: str) -> tuple[list[str], bool] | None:
    """Turn the validator's JSON report into one message per issue, plus its `ok`.

    Returns None when `stdout` is not a report of the shape `{ok: bool, issues: [...]}`.
    """
    try:
        report: object = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(report, dict):
        return None
    fields = cast("dict[str, object]", report)
    ok, issues = fields.get("ok"), fields.get("issues")
    if not isinstance(ok, bool) or not isinstance(issues, list):
        return None
    messages: list[str] = []
    for issue in cast("list[object]", issues):
        if not isinstance(issue, dict):
            return None
        item = cast("dict[str, object]", issue)
        code, severity, text = item.get("code"), item.get("severity"), item.get("message")
        if not (isinstance(code, str) and isinstance(severity, str) and isinstance(text, str)):
            return None
        messages.append(f"{severity.upper()} {code}: {text}")
    return messages, ok
