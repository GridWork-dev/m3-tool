"""The vision critic: ask Codex to judge images against a checklist, and read its verdict.

The critic is a gate, so it fails closed and parses strictly. A verdict is the whole message as
one JSON object, or a message that is one fenced block (```json or bare ```) holding one JSON
object. Anything else is a failed verdict that says why: prose around the JSON, two objects, an
array, a truncation, a repeated key, a missing or non-boolean `pass`, a missing `issues` list.
There is no scanning for an object inside other text, because every such rule left a shape that
passed by accident. `pass: true` next to a blocker issue is not ok. `run_critic` turns a Codex
failure into a failed verdict too, so a caller counts it as a failed round.
"""

import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from m3_pipeline.stages.lib.codex import CodexError, run_codex

Severity = Literal["blocker", "major", "minor"]
Kind = Literal["synth-view", "exterior", "interior", "product"]

_NO_VALID_VERDICT = "critic returned no valid verdict"
# A message that is exactly one fenced block: ```json or a bare ```, a newline, the body, ```.
_FENCE = re.compile(r"^```(?:json)?[ \t]*\n(?P<body>.*?)\s*```$", re.DOTALL)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A JSON object with a repeated key is ambiguous (`{"pass": false, "pass": true}`: the
    last would win), so it does not decode. Applies at every level."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


_DECODER = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys)


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


class _Invalid(Exception):
    """The message is not a valid verdict; the text says why."""


def _failed(text: str, raw: str) -> Verdict:
    return Verdict(False, (Issue("blocker", text, ""),), raw)


def _single_object(message: str) -> dict[str, object]:
    """The one JSON object that `message` is, bare or as a single fenced block.

    `JSONDecoder.decode` consumes the whole text or raises, so prose before or after the object,
    a second object, trailing junk and truncation are all errors. Raises _Invalid.
    """
    text = message.strip()
    if not text:
        raise _Invalid("the message is empty")
    if text.startswith("```"):
        fenced = _FENCE.match(text)
        if fenced is None:
            raise _Invalid("not a single fenced block (```json or bare ```) around the JSON")
        text = fenced.group("body")
    try:
        value = _DECODER.decode(text)
    except json.JSONDecodeError as error:
        raise _Invalid(f"not a single JSON object ({error.msg})") from error
    except RecursionError as error:
        raise _Invalid("the JSON is nested too deeply") from error
    except ValueError as error:  # a repeated key
        raise _Invalid(str(error)) from error
    if not isinstance(value, dict):
        raise _Invalid("the JSON value is not an object")
    return cast("dict[str, object]", value)


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


def _issues(entries: list[object]) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise _Invalid(f"issue {number} is not an object")
        fields = cast("dict[str, object]", entry)
        issues.append(
            Issue(
                _severity(fields.get("severity")),
                _text(fields.get("text")),
                _text(fields.get("fix")),
            )
        )
    return tuple(issues)


def parse_verdict(message: str) -> Verdict:
    """Read the critic's verdict: `{"pass": bool, "issues": [{"severity", "text", "fix"}]}`.

    The message must be exactly that one JSON object, or exactly one fenced block holding it
    (see the module docstring). `ok` is `pass` with no blocker issue; an unknown severity counts
    as a blocker. Any other message becomes a failed verdict with one blocker,
    `critic returned no valid verdict: <reason>`, and `raw` keeps the message. Never raises.
    """
    try:
        obj = _single_object(message)
        passed = obj.get("pass")
        if not isinstance(passed, bool):
            raise _Invalid("`pass` is missing or is not true or false")
        entries = obj.get("issues")
        if not isinstance(entries, list):
            raise _Invalid("`issues` is missing or is not a list")
        issues = _issues(cast("list[object]", entries))
    except _Invalid as invalid:
        return _failed(f"{_NO_VALID_VERDICT}: {invalid}", message)
    ok = passed and all(issue.severity != "blocker" for issue in issues)
    return Verdict(ok, issues, message)


# What the images are, per kind. The order is part of the contract with the caller (see
# `run_critic`): the prompt tells the critic which attachment is which.
_SUBJECT: dict[Kind, str] = {
    "synth-view": (
        "The attached images arrive in a fixed order: every image except the last is a real "
        "reference photo of one car, and the last image is a synthesized candidate view of that "
        "car, made to feed a 3D generator. Compare the candidate against the reference photos: "
        "it must be a faithful, undistorted view of the same car, with the same body shape, "
        "proportions and parts."
    ),
    "exterior": (
        "The attached images show a car's exterior, in pairs: each real reference photo is "
        "followed by a render of the 3D model. Compare each render with the photo just before it."
    ),
    "interior": (
        "The attached images show a car's interior, in pairs: each real reference photo is "
        "followed by a render of the 3D model, including renders from the driver's eye point. "
        "Compare each render with the photo just before it."
    ),
    "product": (
        "The attached images show one car part, such as a wheel, in pairs: each product photo is "
        "followed by a render of the 3D model. Compare each render with the photo just before it."
    ),
}

# Forbidden marks are a blocker only on what was generated, never on the real photos.
_GENERATED: dict[Kind, str] = {
    "synth-view": "the synthesized candidate (the last image)",
    "exterior": "a render",
    "interior": "a render",
    "product": "a render",
}
_PHOTOS: dict[Kind, str] = {
    "synth-view": "reference photos",
    "exterior": "reference photos",
    "interior": "reference photos",
    "product": "product photos",
}


def critic_prompt(kind: Kind, checklist: Sequence[str]) -> str:
    """The prompt for one critic run. `checklist` is what the images must satisfy.

    The attachment order is fixed per kind. `synth-view`: the real reference photos first, the
    synthesized candidate last. `exterior`, `interior` and `product`: pairs, each real photo
    followed by the render to compare with it.
    """
    lines = [
        "You are a strict visual critic for 3D models of cars and car parts.",
        _SUBJECT[kind],
        "",
        "Judge only shape, proportion, parts and forbidden marks. A render is a flat studio "
        "render, so ignore lighting, shading and reflections.",
        "Forbidden marks are badges, roundels, logos and plates (number plates). Any of them on "
        f"{_GENERATED[kind]}, wherever it sits, is a blocker. The {_PHOTOS[kind]} are real and "
        "show real badges, logos and plates: those never count, and you never list one as an "
        "issue.",
        "",
        "Checklist:",
        *(f"- {item}" for item in checklist),
        "",
        "Reply with one JSON object and nothing else: no text before or after it, no second "
        "object and no code fence. Use this shape:",
        '{"pass": false, "issues": [{"severity": "blocker", "text": "what is wrong", '
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

    `images` is in the order `critic_prompt` promises for `kind`: for `synth-view` the real
    reference photos then the synthesized candidate last; otherwise each real photo followed by
    its render. Codex runs read-only: the critic judges, it never writes files. Its last message
    goes to a scratch folder, not `cwd`. A Codex failure (a missing image, no binary, a timeout,
    a nonzero exit, an empty answer) is a failed verdict whose one blocker names the error,
    never a pass and never a raise.
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
