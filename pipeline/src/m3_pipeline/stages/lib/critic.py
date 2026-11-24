"""The vision critic: ask Codex to judge images against a checklist, and read its verdict.

The critic is a gate, so it fails closed. `parse_verdict` never raises and never passes by
default: prose, an empty message, half-formed JSON, a missing `pass` field, a `pass` that is not
a boolean and `pass: true` next to a blocker issue all give a failed verdict. `run_critic` turns
a Codex failure into a failed verdict too, so a caller counts it as a failed round.
"""

import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from m3_pipeline.stages.lib.codex import CodexError, run_codex

Severity = Literal["blocker", "major", "minor"]
Kind = Literal["synth-view", "exterior", "interior", "product"]

_NO_VALID_VERDICT = "critic returned no valid verdict"
_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class Issue:
    severity: Severity
    text: str
    fix: str


@dataclass(frozen=True)
class Verdict:
    ok: bool
    issues: tuple[Issue, ...]
    raw: str


def _failed(text: str, raw: str) -> Verdict:
    return Verdict(False, (Issue("blocker", text, ""),), raw)


def _last_object(message: str) -> dict[str, object] | None:
    """The last top-level JSON object in `message`, wherever it sits (bare, in a fence, in prose).

    Scans every `{` and skips past an object once it decodes, so the objects nested inside an
    `issues` list are never taken for the verdict. A `{` that does not decode voids any earlier
    object: a half-formed object after a complete one means the final answer is broken, and a
    gate must not pass on the earlier draft.
    """
    last: dict[str, object] | None = None
    start = message.find("{")
    while start != -1:
        try:
            value, end = _DECODER.raw_decode(message, start)
        except ValueError, RecursionError:
            last = None
            start = message.find("{", start + 1)
            continue
        if isinstance(value, dict):
            last = cast("dict[str, object]", value)
        start = message.find("{", end)
    return last


def _severity(value: object) -> Severity:
    """`major` and `minor` as written (ignoring case and spaces); anything else is a blocker."""
    if isinstance(value, str):
        name = value.strip().lower()
        if name == "major":
            return "major"
        if name == "minor":
            return "minor"
    return "blocker"


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def parse_verdict(message: str) -> Verdict:
    """Read the critic's verdict: `{"pass": bool, "issues": [{"severity", "text", "fix"}]}`.

    `ok` is `pass` with no blocker issue. An unknown severity counts as a blocker. Any message
    without a valid verdict (no JSON object, no boolean `pass`, no `issues` list of objects)
    becomes a failed verdict with one blocker, `critic returned no valid verdict`. Never raises.
    """
    obj = _last_object(message)
    if obj is None:
        return _failed(_NO_VALID_VERDICT, message)
    passed = obj.get("pass")
    entries = obj.get("issues")
    if not isinstance(passed, bool) or not isinstance(entries, list):
        return _failed(_NO_VALID_VERDICT, message)
    issues: list[Issue] = []
    for entry in cast("list[object]", entries):
        if not isinstance(entry, dict):
            return _failed(_NO_VALID_VERDICT, message)
        fields = cast("dict[str, object]", entry)
        issues.append(
            Issue(
                _severity(fields.get("severity")),
                _text(fields.get("text")),
                _text(fields.get("fix")),
            )
        )
    ok = passed and all(issue.severity != "blocker" for issue in issues)
    return Verdict(ok, tuple(issues), message)


_SUBJECT: dict[Kind, str] = {
    "synth-view": (
        "The attached images are synthesized views of one car, made to feed a 3D generator. "
        "Check that each view is a faithful, undistorted view of the same single car."
    ),
    "exterior": (
        "The attached images show a car's exterior: real reference photos, each followed by a "
        "render of the 3D model. Compare each render with its photo, in the order given."
    ),
    "interior": (
        "The attached images show a car's interior: real reference photos, each followed by a "
        "render of the 3D model, including the driver's-eye view. Compare each render with its "
        "photo, in the order given."
    ),
    "product": (
        "The attached images show one car part, such as a wheel: product photos, each followed "
        "by a render of the 3D model. Compare each render with its photo, in the order given."
    ),
}


def critic_prompt(kind: Kind, checklist: Sequence[str]) -> str:
    """The prompt for one critic run. `checklist` is what the images must satisfy."""
    lines = [
        "You are a strict visual critic for 3D models of cars and car parts.",
        _SUBJECT[kind],
        "",
        "Judge only shape, proportion, parts and forbidden marks. Forbidden marks are badges, "
        "roundels, logos and plates (number plates): any of them, anywhere, is a blocker. A "
        "render is a flat studio render, so ignore lighting, shading and reflections.",
        "",
        "Checklist:",
        *(f"- {item}" for item in checklist),
        "",
        "Reply with one JSON object and nothing else, in this shape:",
        '{"pass": true, "issues": [{"severity": "blocker", "text": "what is wrong", '
        '"fix": "the concrete change to make"}]}',
        '"severity" is one of "blocker" (fails the model on its own), "major" (a clear departure '
        'from the checklist) or "minor" (cosmetic). List every issue you find, with a fix for '
        'each, and use an empty "issues" list when there are none. Set "pass" to false when any '
        "issue is a blocker.",
    ]
    return "\n".join(lines)


def run_critic(
    kind: Kind, checklist: Sequence[str], images: Sequence[Path], *, cwd: Path
) -> Verdict:
    """Run the critic on `images` and return its verdict.

    Codex runs read-only: the critic judges, it never writes files. Its last message goes to a
    scratch folder, not `cwd`. A Codex failure (no binary, timeout, nonzero exit, empty answer)
    is a failed verdict whose one blocker names the error, never a pass and never a raise.
    """
    prompt = critic_prompt(kind, checklist)
    with tempfile.TemporaryDirectory(prefix="m3-critic-") as scratch:
        try:
            message = run_codex(
                prompt,
                images,
                cwd=cwd,
                last_message=Path(scratch) / "last.md",
                sandbox="read-only",
            )
        except CodexError as error:
            return _failed(f"codex critic failed: {error}", str(error))
    return parse_verdict(message)
