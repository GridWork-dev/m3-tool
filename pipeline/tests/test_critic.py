import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast, get_args

import pytest

import m3_pipeline.stages.lib.critic as critic
from m3_pipeline.stages.lib.codex import CodexError
from m3_pipeline.stages.lib.critic import Issue, Verdict, critic_prompt, parse_verdict, run_critic

Kind = Literal["synth-view", "exterior", "interior", "product"]
KINDS = cast("tuple[Kind, ...]", get_args(Kind))
NO_VALID_VERDICT = "critic returned no valid verdict"


def _verdict_json(passed: object, issues: Sequence[object] = ()) -> str:
    return json.dumps({"pass": passed, "issues": list(issues)})


def _issue(severity: str, text: str = "t", fix: str = "f") -> dict[str, str]:
    return {"severity": severity, "text": text, "fix": fix}


def _assert_failed_with_no_valid_verdict(verdict: Verdict, raw: str) -> None:
    assert verdict.ok is False
    assert verdict.issues == (Issue("blocker", NO_VALID_VERDICT, ""),)
    assert verdict.raw == raw


# --- parse_verdict: garbage never passes ----------------------------------------------------


def test_garbage_message_is_a_failed_verdict_not_a_pass() -> None:
    assert parse_verdict("Looks great to me!").ok is False


@pytest.mark.parametrize(
    "message",
    [
        "Looks great to me!",
        "pass",
        "",
        "   \n\t ",
        '{"pass": true, "issues": [',  # half-formed
        '{"pass": tru',
        '{"pass": true, "issues": [{"severity": "minor", "text": "x"',
        "```json\n{not json}\n```",  # a fenced block with junk
        "```json\n```",
        "```\nlooks fine\n```",
        "[]",
        '["pass", true]',
        '"pass"',
        "null",
        "true",
        "{}",
        '{"pass": true, "issues": []} then {broken',  # a good verdict, then a broken object
    ],
)
def test_prose_empty_half_formed_and_junk_messages_fail(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


def test_parse_verdict_never_raises_on_odd_input() -> None:
    for message in ("\x00", "{" * 5000, "}" * 5000, "```" * 100, '{"pass": NaN}', "\ud83d"):
        assert parse_verdict(message).ok is False


def test_parse_verdict_rejects_a_missing_pass_field() -> None:
    message = json.dumps({"issues": []})
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


@pytest.mark.parametrize("passed", ["true", "yes", 1, 0, None, [], {}])
def test_parse_verdict_rejects_a_pass_that_is_not_a_boolean(passed: object) -> None:
    message = _verdict_json(passed)
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


@pytest.mark.parametrize(
    "message",
    [
        '{"pass": true}',
        '{"pass": false}',
        '{"pass": true, "issues": "none"}',
        '{"pass": true, "issues": null}',
        '{"pass": true, "issues": {"severity": "minor"}}',
        '{"pass": true, "issues": ["looks off"]}',
        '{"pass": true, "issues": [null]}',
    ],
)
def test_parse_verdict_rejects_a_missing_or_malformed_issues_list(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


# --- parse_verdict: where the JSON may sit --------------------------------------------------


def test_parse_verdict_reads_a_bare_object() -> None:
    verdict = parse_verdict(_verdict_json(True))
    assert verdict.ok is True and verdict.issues == ()


def test_parse_verdict_reads_json_inside_a_code_fence() -> None:
    message = "```json\n" + _verdict_json(False, [_issue("major", "roof too tall")]) + "\n```"
    verdict = parse_verdict(message)
    assert verdict.ok is False
    assert verdict.issues == (Issue("major", "roof too tall", "f"),)
    assert verdict.raw == message


def test_parse_verdict_reads_json_inside_a_bare_fence() -> None:
    verdict = parse_verdict("```\n" + _verdict_json(True) + "\n```")
    assert verdict.ok is True


def test_parse_verdict_reads_json_wrapped_in_prose() -> None:
    message = (
        "Here is my verdict, as asked:\n"
        + _verdict_json(False, [_issue("blocker", "a roundel on the hood")])
        + "\nI hope that helps."
    )
    verdict = parse_verdict(message)
    assert verdict.ok is False
    assert [i.text for i in verdict.issues] == ["a roundel on the hood"]


def test_parse_verdict_takes_the_last_json_object() -> None:
    earlier_fail = _verdict_json(False, [_issue("blocker", "first draft")])
    later_pass = _verdict_json(True)
    assert parse_verdict(f"{earlier_fail}\nOn reflection:\n{later_pass}").ok is True
    assert parse_verdict(f"{later_pass}\nOn reflection:\n{earlier_fail}").ok is False


def test_nested_issue_objects_are_not_mistaken_for_the_verdict() -> None:
    message = _verdict_json(False, [_issue("minor", "a"), _issue("major", "b")])
    verdict = parse_verdict(message)
    assert [i.text for i in verdict.issues] == ["a", "b"]


def test_braces_in_the_prose_before_the_verdict_are_ignored() -> None:
    verdict = parse_verdict("The {hood} is fine.\n" + _verdict_json(True))
    assert verdict.ok is True


# --- parse_verdict: severity and ok ---------------------------------------------------------


def test_pass_true_with_a_blocker_issue_is_not_ok() -> None:
    verdict = parse_verdict(_verdict_json(True, [_issue("blocker", "a BMW badge on the grille")]))
    assert verdict.ok is False
    assert verdict.issues == (Issue("blocker", "a BMW badge on the grille", "f"),)


def test_pass_true_with_only_major_and_minor_issues_is_ok_and_keeps_them() -> None:
    verdict = parse_verdict(_verdict_json(True, [_issue("major", "a"), _issue("minor", "b")]))
    assert verdict.ok is True
    assert [i.severity for i in verdict.issues] == ["major", "minor"]


def test_pass_false_with_no_blocker_is_still_not_ok() -> None:
    assert parse_verdict(_verdict_json(False, [_issue("minor")])).ok is False


@pytest.mark.parametrize("severity", ["critical", "fatal", "", "BLOCKING", 7, None, ["blocker"]])
def test_unknown_severity_is_treated_as_a_blocker(severity: object) -> None:
    verdict = parse_verdict(_verdict_json(True, [{"severity": severity, "text": "t", "fix": "f"}]))
    assert verdict.ok is False
    assert [i.severity for i in verdict.issues] == ["blocker"]


def test_a_missing_severity_is_treated_as_a_blocker() -> None:
    verdict = parse_verdict(_verdict_json(True, [{"text": "t", "fix": "f"}]))
    assert verdict.ok is False and verdict.issues[0].severity == "blocker"


def test_severity_is_matched_ignoring_case_and_spaces() -> None:
    verdict = parse_verdict(_verdict_json(True, [_issue(" Major "), _issue("MINOR")]))
    assert verdict.ok is True
    assert [i.severity for i in verdict.issues] == ["major", "minor"]


def test_pass_false_keeps_every_issue_and_fix() -> None:
    issues = [
        _issue("blocker", "roundel on the steering wheel", "remove the roundel"),
        _issue("major", "wheelbase too short", "stretch the middle by 4 percent"),
        _issue("minor", "mirror stalk thick", "thin the stalk"),
    ]
    verdict = parse_verdict(_verdict_json(False, issues))
    assert verdict.ok is False
    assert verdict.issues == (
        Issue("blocker", "roundel on the steering wheel", "remove the roundel"),
        Issue("major", "wheelbase too short", "stretch the middle by 4 percent"),
        Issue("minor", "mirror stalk thick", "thin the stalk"),
    )


def test_an_issue_without_text_or_fix_keeps_empty_strings() -> None:
    verdict = parse_verdict(
        _verdict_json(False, [{"severity": "major"}, {"severity": "minor", "text": 5}])
    )
    assert verdict.issues == (Issue("major", "", ""), Issue("minor", "", ""))


# --- critic_prompt --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_critic_prompt_names_the_checklist_and_the_forbidden_marks(kind: Kind) -> None:
    checklist = ["flared fenders in four places", "no center-exit exhaust"]
    prompt = critic_prompt(kind, checklist)
    for item in checklist:
        assert item in prompt
    for mark in ("badges", "roundels", "logos", "plates"):
        assert mark in prompt


@pytest.mark.parametrize("kind", KINDS)
def test_critic_prompt_states_the_fixed_rules(kind: Kind) -> None:
    prompt = critic_prompt(kind, ["x"])
    assert "shape, proportion, parts and forbidden marks" in prompt
    assert "flat studio render" in prompt and "ignore lighting" in prompt
    assert "one JSON object and nothing else" in prompt
    for field in ('"pass"', '"issues"', '"severity"', '"text"', '"fix"'):
        assert field in prompt
    for severity in ("blocker", "major", "minor"):
        assert severity in prompt


def test_critic_prompt_differs_by_kind() -> None:
    prompts = {critic_prompt(kind, ["x"]) for kind in KINDS}
    assert len(prompts) == len(KINDS)


def test_critic_prompt_with_no_checklist_still_asks_for_the_verdict() -> None:
    assert "one JSON object and nothing else" in critic_prompt("exterior", [])


# --- run_critic -----------------------------------------------------------------------------


class FakeCodex:
    """Stands in for `critic.run_codex`: records its arguments and returns a canned message."""

    def __init__(self, message: str | None = None, raises: Exception | None = None) -> None:
        self.message = message
        self.raises = raises
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        prompt: str,
        images: Sequence[Path],
        *,
        cwd: Path,
        last_message: Path,
        timeout_s: int = 900,
        sandbox: str = "workspace-write",
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "images": list(images),
                "cwd": cwd,
                "last_message": last_message,
                "sandbox": sandbox,
                "parent_existed": last_message.parent.is_dir(),
            }
        )
        if self.raises is not None:
            raise self.raises
        assert self.message is not None
        return self.message


def test_run_critic_sends_the_prompt_and_images_to_codex_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCodex(_verdict_json(True))
    monkeypatch.setattr(critic, "run_codex", fake)
    images = [tmp_path / "photo.png", tmp_path / "render.png"]

    verdict = run_critic("exterior", ["wide hips"], images, cwd=tmp_path)

    assert verdict.ok is True
    (call,) = fake.calls
    assert call["prompt"] == critic_prompt("exterior", ["wide hips"])
    assert call["images"] == images
    assert call["cwd"] == tmp_path
    assert call["sandbox"] == "read-only"
    last = call["last_message"]
    assert isinstance(last, Path)
    assert call["parent_existed"] is True
    assert not last.resolve().is_relative_to(tmp_path.resolve())  # never lands in cwd
    assert not last.parent.exists()  # and its folder is gone after the call


def test_run_critic_returns_a_failed_verdict_when_codex_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(critic, "run_codex", FakeCodex(raises=CodexError("codex exited 1: boom")))
    verdict = run_critic("product", ["plain center cap"], [tmp_path / "w.png"], cwd=tmp_path)
    assert verdict.ok is False
    assert len(verdict.issues) == 1
    (issue,) = verdict.issues
    assert issue.severity == "blocker" and "codex exited 1: boom" in issue.text
    assert "codex exited 1: boom" in verdict.raw


@pytest.mark.parametrize("message", ["Looks great to me!", "", '{"pass": true,'])
def test_run_critic_fails_when_codex_answers_with_garbage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    monkeypatch.setattr(critic, "run_codex", FakeCodex(message))
    verdict = run_critic("interior", ["x"], [tmp_path / "a.png"], cwd=tmp_path)
    _assert_failed_with_no_valid_verdict(verdict, message)


def test_run_critic_returns_the_parsed_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = (
        "```json\n"
        + _verdict_json(False, [_issue("major", "grille too wide", "narrow it")])
        + "\n```"
    )
    monkeypatch.setattr(critic, "run_codex", FakeCodex(message))
    verdict = run_critic("synth-view", ["x"], [tmp_path / "a.png"], cwd=tmp_path)
    assert verdict.ok is False
    assert verdict.issues == (Issue("major", "grille too wide", "narrow it"),)
    assert verdict.raw == message
