import json
import time
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


def _assert_failed_with_no_valid_verdict(verdict: Verdict, raw: str, reason: str = "") -> None:
    """A failed verdict: one blocker that starts `critic returned no valid verdict: ` and names
    the reason (`reason`, when given, must appear in it); `raw` is kept."""
    assert verdict.ok is False
    (issue,) = verdict.issues
    assert issue.severity == "blocker" and issue.fix == ""
    assert issue.text.startswith(NO_VALID_VERDICT + ": ")
    assert reason in issue.text
    assert verdict.raw == raw


PASSING = _verdict_json(True)
FAILING = _verdict_json(False, [_issue("major", "roof too tall", "lower the roof")])


# --- parse_verdict: exactly two accepted forms ----------------------------------------------


def test_garbage_message_is_a_failed_verdict_not_a_pass() -> None:
    assert parse_verdict("Looks great to me!").ok is False


def test_parse_verdict_reads_a_bare_object() -> None:
    verdict = parse_verdict(PASSING)
    assert verdict.ok is True and verdict.issues == () and verdict.raw == PASSING


def test_parse_verdict_trims_whitespace_around_a_bare_object() -> None:
    assert parse_verdict("\n\n  " + PASSING + " \t\n").ok is True


def test_parse_verdict_reads_json_inside_a_code_fence() -> None:
    message = "```json\n" + FAILING + "\n```"
    verdict = parse_verdict(message)
    assert verdict.ok is False
    assert verdict.issues == (Issue("major", "roof too tall", "lower the roof"),)
    assert verdict.raw == message


@pytest.mark.parametrize(
    "message",
    [
        "```\n" + PASSING + "\n```",  # a bare fence
        "```json\n" + PASSING + "\n```",
        "\n  ```json\n" + PASSING + "\n```\n\n",  # whitespace around the whole message
        "```json\n" + PASSING + "```",  # the closing fence right after the JSON
        "```json  \n\n" + PASSING + "\n\n```",
        "```json\n" + json.dumps(json.loads(PASSING), indent=2) + "\n```",  # a pretty-printed body
    ],
)
def test_parse_verdict_accepts_a_single_fenced_block(message: str) -> None:
    verdict = parse_verdict(message)
    assert verdict.ok is True and verdict.issues == ()


def test_nested_issue_objects_are_part_of_the_one_verdict_object() -> None:
    verdict = parse_verdict(_verdict_json(False, [_issue("minor", "a"), _issue("major", "b")]))
    assert [i.text for i in verdict.issues] == ["a", "b"]


def test_braces_inside_strings_do_not_confuse_the_parser() -> None:
    verdict = parse_verdict(_verdict_json(True, [_issue("minor", 'a } b { c " d', "fix {}")]))
    assert verdict.ok is True and verdict.issues[0].text == 'a } b { c " d'


# --- parse_verdict: every other shape is a failed verdict, with a reason ---------------------


@pytest.mark.parametrize(
    "message",
    [
        "Looks great to me!",
        "pass",
        "{}",
        "[]",
        '["pass", true]',
        '"pass"',
        "null",
        "true",
        "42",
    ],
)
def test_prose_and_non_verdict_json_fail(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


@pytest.mark.parametrize("message", ["", "   \n\t ", "```json\n```", "```\n\n```"])
def test_an_empty_message_or_an_empty_fence_fails(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


def test_the_empty_message_names_its_reason() -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict("  \n"), "  \n", "empty")


def test_prose_before_the_json_fails() -> None:
    message = "Here is my verdict:\n" + PASSING
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


def test_prose_after_the_json_fails() -> None:
    message = PASSING + "\nI hope that helps."
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "Extra data")


def test_prose_on_both_sides_of_the_json_fails() -> None:
    message = "Verdict:\n" + PASSING + "\nHope that helps."
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


@pytest.mark.parametrize(
    "first, second",
    [(FAILING, PASSING), (PASSING, FAILING), (PASSING, PASSING), (PASSING, "{}")],
)
def test_two_objects_fail_in_either_order(first: str, second: str) -> None:
    for message in (
        f"{first}\n{second}",
        f"{first}{second}",
        f"{first}\n\nOn reflection:\n{second}",
    ):
        _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


def test_a_complete_verdict_followed_by_a_broken_object_fails() -> None:
    for tail in ("{broken", "{oops}", "{"):
        message = PASSING + "\n" + tail
        _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


@pytest.mark.parametrize(
    "message",
    [
        '[{"pass": true, "issues": []}',  # an array-wrapped verdict, truncated
        '[{"pass": true, "issues": []}]',
        '[{"pass": true, "issues": []}, {"pass": true, "issues": []}]',
        "```json\n" + '[{"pass": true, "issues": []}]' + "\n```",
        '{"verdict": {"pass": true, "issues": []}}',  # wrapped in another object
    ],
)
def test_a_verdict_wrapped_in_an_array_or_another_object_fails(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


def test_a_json_array_names_its_reason() -> None:
    message = '[{"pass": true, "issues": []}]'
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "not an object")


@pytest.mark.parametrize(
    "message",
    [
        "```json\n" + PASSING + "\n```\nHope that helps.",  # a fence plus trailing prose
        "Here you go:\n```json\n" + PASSING + "\n```",  # leading prose plus a fence
        "Here you go:\n```json\n" + PASSING + "\n```\nHope that helps.",
        "```json\n" + FAILING + "\n```\n```json\n" + PASSING + "\n```",  # two fenced blocks
        "```json\n" + PASSING + "\n```\n" + PASSING,  # a fence, then a bare object
        "```json\n" + PASSING + "\n",  # an unclosed fence
        "```json\n" + PASSING + "\n``",
        "``` " + PASSING + " ```",  # no newline after the opening fence
        "```python\n" + PASSING + "\n```",  # another language tag
        "```jsonl\n" + PASSING + "\n```",
        "```JSON\n" + PASSING + "\n```",
        "```json\nThe verdict is:\n" + PASSING + "\n```",  # prose inside the fence
        "```json\n{not json}\n```",
        "```\nlooks fine\n```",
        "`" + PASSING + "`",  # inline code, not a fence
    ],
)
def test_a_fence_that_is_not_one_clean_block_around_one_object_fails(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


def test_a_malformed_fence_names_its_reason() -> None:
    message = "```json\n" + PASSING + "\n```\nHope that helps."
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "fence")


def test_a_truncated_verdict_fails() -> None:
    message = '{"pass": false, "issues": [{"pass": true, "issues": []}'
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message)


@pytest.mark.parametrize(
    "verdict", [PASSING, _verdict_json(True, [_issue("minor", "a } b", "fix"), _issue("major")])]
)
def test_every_truncation_of_a_passing_verdict_fails_bare_and_fenced(verdict: str) -> None:
    for cut in range(len(verdict)):
        piece = verdict[:cut]
        bare = parse_verdict(piece)
        assert bare.ok is False, piece
        assert bare.issues[0].text.startswith(NO_VALID_VERDICT), piece
        fenced = parse_verdict("```json\n" + piece + "\n```")
        assert fenced.ok is False, piece
        assert fenced.issues[0].text.startswith(NO_VALID_VERDICT), piece


def test_parse_verdict_never_raises_on_odd_input() -> None:
    for message in ("\x00", "{" * 5000, "}" * 5000, "```" * 100, '{"pass": NaN}', "\ud83d"):
        assert parse_verdict(message).ok is False


def test_parse_time_is_linear_on_large_garbage() -> None:
    # A degenerate model loop must not hang the gate: strict decoding looks at the text once.
    started = time.monotonic()
    for message in ("{x}" * 200000, "{" * 200000, '{"a":[' * 20000):
        assert parse_verdict(message).ok is False
    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize(
    "message",
    [
        '{"pass": false, "pass": true, "issues": []}',
        '{"pass": true, "pass": false, "issues": []}',
        '{"pass": true, "issues": [{"severity": "blocker", "text": "t"}], "issues": []}',
        '{"pass": true, "issues": [{"severity": "blocker", "severity": "minor", "text": "t"}]}',
        '{"pass": true, "issues": [], "extra": {"a": 1, "a": 2}}',  # a duplicate at any level
    ],
)
def test_duplicate_json_keys_are_a_failed_verdict(message: str) -> None:
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "duplicate key")


def test_parse_verdict_rejects_a_missing_pass_field() -> None:
    message = json.dumps({"issues": []})
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "pass")


@pytest.mark.parametrize("passed", ["true", "yes", 1, 0, None, [], {}])
def test_parse_verdict_rejects_a_pass_that_is_not_a_boolean(passed: object) -> None:
    message = _verdict_json(passed)
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "pass")


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
    _assert_failed_with_no_valid_verdict(parse_verdict(message), message, "issue")


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


@pytest.mark.parametrize("kind", KINDS)
def test_critic_prompt_spells_out_that_only_one_bare_object_is_accepted(kind: Kind) -> None:
    prompt = critic_prompt(kind, ["x"])
    assert "no text before or after it" in prompt
    assert "no second object" in prompt
    assert "no code fence" in prompt


def test_synth_view_prompt_fixes_the_attachment_order_and_asks_for_a_comparison() -> None:
    prompt = critic_prompt("synth-view", ["x"])
    assert "every image except the last is a real reference photo" in prompt
    assert "the last image is a synthesized candidate view" in prompt
    assert "Compare the candidate against the reference photos" in prompt


@pytest.mark.parametrize("kind", ["exterior", "interior", "product"])
def test_paired_prompts_say_each_photo_is_followed_by_its_render(kind: Kind) -> None:
    prompt = critic_prompt(kind, ["x"])
    assert "each" in prompt and "followed by a render" in prompt
    assert "Compare each render with the photo just before it" in prompt


@pytest.mark.parametrize("kind", KINDS)
def test_forbidden_marks_are_a_blocker_only_on_the_candidate_never_on_the_reference_photos(
    kind: Kind,
) -> None:
    prompt = critic_prompt(kind, ["x"])
    rule = next(line for line in prompt.splitlines() if line.startswith("Forbidden marks"))
    target = "the synthesized candidate" if kind == "synth-view" else "a render"
    assert f"Any of them on {target}" in rule and "is a blocker" in rule
    assert "any of them, anywhere, is a blocker" not in prompt  # the old, unscoped rule
    photos = "product photos" if kind == "product" else "reference photos"
    assert f"The {photos} are real and show real badges, logos and plates" in rule
    assert "never count" in rule and "never list one as an issue" in rule


@pytest.mark.parametrize("kind", KINDS)
def test_critic_prompt_example_is_a_consistent_verdict(kind: Kind) -> None:
    # The example teaches the shape: `pass` must be false next to a blocker, or a critic that
    # copies it literally contradicts the prompt's own rule.
    lines = [line for line in critic_prompt(kind, ["x"]).splitlines() if line.startswith("{")]
    assert len(lines) == 1
    example = cast("dict[str, object]", json.loads(lines[0]))
    entries = cast("list[dict[str, str]]", example["issues"])
    has_blocker = any(entry["severity"] == "blocker" for entry in entries)
    assert example["pass"] is (not has_blocker)
    assert parse_verdict(lines[0]).raw == lines[0]
    assert [i.severity for i in parse_verdict(lines[0]).issues] == [e["severity"] for e in entries]


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
