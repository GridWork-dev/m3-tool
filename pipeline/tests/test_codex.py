import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

import pytest

import m3_pipeline.stages.lib.codex as codex
from m3_pipeline.stages.lib.codex import (
    CodexError,
    build_argv,
    child_env,
    codex_binary,
    run_codex,
)

FAKE_BINARY = Path("/opt/fake/codex")


STATUS_OK = "Logged in using ChatGPT\n"  # what `codex login status` prints, on stderr


class FakeRun:
    """Stands in for `codex._run`: records every call, and writes the `-o` file like Codex.

    `calls` holds the exec calls only and `status_calls` the `codex login status` preflights;
    `sequence` is the order they came in. The status output defaults to the real ChatGPT one.
    """

    def __init__(
        self,
        *,
        message: str | None = "ok\n",
        returncode: int = 0,
        stderr: str = "",
        raises: BaseException | None = None,
        status_stdout: str = "",
        status_stderr: str = STATUS_OK,
        status_code: int = 0,
        status_raises: BaseException | None = None,
    ) -> None:
        self.message = message
        self.returncode = returncode
        self.stderr = stderr
        self.raises = raises
        self.status_stdout = status_stdout
        self.status_stderr = status_stderr
        self.status_code = status_code
        self.status_raises = status_raises
        self.calls: list[dict[str, object]] = []
        self.status_calls: list[dict[str, object]] = []
        self.sequence: list[str] = []

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout_s: int | None = None,
        stdin_devnull: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        record: dict[str, object] = {
            "cmd": list(cmd),
            "cwd": cwd,
            "timeout_s": timeout_s,
            "stdin_devnull": stdin_devnull,
            "env": None if env is None else dict(env),
        }
        if list(cmd)[1:3] == ["login", "status"]:
            self.status_calls.append(record)
            self.sequence.append("status")
            if self.status_raises is not None:
                raise self.status_raises
            return subprocess.CompletedProcess(
                list(cmd), self.status_code, self.status_stdout, self.status_stderr
            )
        self.calls.append(record)
        self.sequence.append("exec")
        if self.raises is not None:
            raise self.raises
        if self.message is not None:
            # Like Codex, resolve a relative `-o` path against the child's own working directory.
            target = Path(cmd[list(cmd).index("-o") + 1])
            if not target.is_absolute():
                target = (cwd or Path.cwd()) / target
            # The real CLI does not create the folder: with it missing, `codex exec` exits 0, prints
            # "Failed to write last message file" and leaves nothing behind.
            if target.parent.is_dir():
                target.write_text(self.message, "utf-8")
        return subprocess.CompletedProcess(list(cmd), self.returncode, "headers\n", self.stderr)


def _image(folder: Path, name: str = "view.png") -> Path:
    """An image file for `run_codex` to attach (its bytes are never decoded here)."""
    path = folder / name
    path.write_bytes(b"\x89PNG")
    return path


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeRun) -> FakeRun:
    """Replace the process runner and the binary lookup: no test starts or looks for Codex."""
    monkeypatch.setattr(codex, "_run", fake)

    def fake_binary(env: Mapping[str, str] | None = None) -> Path:
        return FAKE_BINARY

    monkeypatch.setattr(codex, "codex_binary", fake_binary)
    return fake


# --- build_argv -----------------------------------------------------------------------------


def test_argv_puts_the_prompt_before_every_image_flag() -> None:
    argv = build_argv(
        Path("/bin/codex"), "make views", Path("/tmp/last.md"), [Path("a.png"), Path("b.png")]
    )
    assert argv.index("make views") < argv.index("-i") and argv.count("-i") == 2
    assert argv[:7] == [
        "/bin/codex",
        "exec",
        "-s",
        "workspace-write",
        "--ephemeral",
        "--skip-git-repo-check",
        "-o",
    ]


def test_argv_repeats_dash_i_once_per_image_in_order() -> None:
    argv = build_argv(
        Path("/bin/codex"),
        "p",
        Path("/tmp/last.md"),
        [Path("a.png"), Path("b.png"), Path("c.png")],
    )
    assert argv[7:] == [
        "/tmp/last.md",
        "-c",
        'forced_login_method="chatgpt"',
        "p",
        "-i",
        "a.png",
        "-i",
        "b.png",
        "-i",
        "c.png",
    ]


def test_argv_forces_the_chatgpt_login_in_codex_itself() -> None:
    # Belt and braces next to the `codex login status` preflight: with this config key, Codex
    # refuses API-key credentials at exec time (verified on 0.167.0: exit 1, no request).
    for sandbox in ("read-only", "workspace-write"):
        argv = build_argv(Path("/bin/codex"), "p", Path("/tmp/last.md"), [], sandbox=sandbox)
        assert argv.count("-c") == 1
        assert argv[argv.index("-c") + 1] == 'forced_login_method="chatgpt"'
        assert argv.index("-c") < argv.index("p")


def test_argv_without_images_has_no_image_flag() -> None:
    argv = build_argv(Path("/bin/codex"), "p", Path("/tmp/last.md"), [])
    assert "-i" not in argv and argv[-1] == "p"


@pytest.mark.parametrize("sandbox", ["read-only", "workspace-write"])
def test_argv_takes_the_sandbox_mode_after_dash_s(
    sandbox: Literal["read-only", "workspace-write"],
) -> None:
    argv = build_argv(Path("/bin/codex"), "p", Path("/tmp/last.md"), [], sandbox=sandbox)
    assert argv[argv.index("-s") + 1] == sandbox


# --- codex_binary ---------------------------------------------------------------------------


def _real_and_link(tmp_path: Path, link_dir: str = "bin") -> tuple[Path, Path]:
    real = tmp_path / "cask" / "0.1.0" / "codex"
    real.parent.mkdir(parents=True)
    real.write_text("#!/bin/sh\n", "utf-8")
    real.chmod(0o755)
    link = tmp_path / link_dir / "codex"
    link.parent.mkdir()
    link.symlink_to(real)
    return real, link


def test_codex_binary_is_resolved_through_realpath(tmp_path: Path) -> None:
    real, link = _real_and_link(tmp_path)
    found = codex_binary({"PATH": str(link.parent)})
    assert found == Path(os.path.realpath(real))
    assert found != link


def test_codex_binary_prefers_the_env_override(tmp_path: Path) -> None:
    on_path_real, on_path_link = _real_and_link(tmp_path, "bin")
    override = tmp_path / "other" / "codex"
    override.parent.mkdir()
    override.write_text("#!/bin/sh\n", "utf-8")
    env = {"PATH": str(on_path_link.parent), "M3_CODEX_BIN": str(override)}
    assert codex_binary(env) == Path(os.path.realpath(override))
    assert codex_binary(env) != Path(os.path.realpath(on_path_real))


def test_codex_binary_resolves_an_override_that_is_a_symlink(tmp_path: Path) -> None:
    real, link = _real_and_link(tmp_path)
    assert codex_binary({"PATH": "", "M3_CODEX_BIN": str(link)}) == Path(os.path.realpath(real))


def test_codex_binary_ignores_an_empty_override(tmp_path: Path) -> None:
    real, link = _real_and_link(tmp_path)
    env = {"PATH": str(link.parent), "M3_CODEX_BIN": ""}
    assert codex_binary(env) == Path(os.path.realpath(real))


def test_codex_binary_missing_everywhere_names_the_override_variable(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CodexError, match="M3_CODEX_BIN"):
        codex_binary({"PATH": str(empty)})


# --- child_env ------------------------------------------------------------------------------


def test_child_env_drops_openai_and_anthropic_api_keys() -> None:
    base = {
        "OPENAI_API_KEY": "sk-openai",
        "ANTHROPIC_API_KEY": "sk-anthropic",
        "HOME": "/home/x",
        "PATH": "/usr/bin",
    }
    assert child_env(base) == {"HOME": "/home/x", "PATH": "/usr/bin"}
    assert "OPENAI_API_KEY" in base  # the caller's mapping is left alone


@pytest.mark.parametrize("name", ["CODEX_API_KEY", "CODEX_ACCESS_TOKEN"])
def test_child_env_drops_the_codex_credential_overrides(name: str) -> None:
    # `codex exec` calls the API with CODEX_API_KEY instead of the ChatGPT login (verified: a
    # dummy value gave a 401), and CODEX_ACCESS_TOKEN is a second override.
    base = {name: "secret", "OPENAI_API_KEY": "x", "HOME": "/home/x"}
    assert child_env(base) == {"HOME": "/home/x"}


def test_run_codex_hands_the_child_an_environment_without_the_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "token")
    monkeypatch.setenv("M3_TEST_MARKER", "kept")
    fake = _install(monkeypatch, FakeRun())
    run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    env = fake.calls[0]["env"]
    assert isinstance(env, dict)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        assert name not in env
    assert env["M3_TEST_MARKER"] == "kept"


# --- run_codex ------------------------------------------------------------------------------


def test_run_codex_passes_devnull_stdin_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch, FakeRun(message="  the answer \n"))
    last = tmp_path / "out" / "last.md"
    work = tmp_path / "work"
    work.mkdir()
    image = _image(tmp_path)

    answer = run_codex("do it", [image], cwd=work, last_message=last)

    assert answer == "the answer"
    (call,) = fake.calls
    assert call["stdin_devnull"] is True
    assert call["cwd"] == work
    assert call["timeout_s"] == 900
    assert call["cmd"] == build_argv(FAKE_BINARY, "do it", last, [image])


def test_run_codex_passes_the_timeout_and_sandbox_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch, FakeRun())
    run_codex(
        "p", [], cwd=tmp_path, last_message=tmp_path / "last.md", timeout_s=42, sandbox="read-only"
    )
    call = fake.calls[0]
    assert call["timeout_s"] == 42
    cmd = cast("list[str]", call["cmd"])
    assert cmd[cmd.index("-s") + 1] == "read-only"


def test_run_codex_nonzero_exit_raises_with_the_stderr_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stderr = "FIRST-LINE-NOISE\n" + "x" * 5000 + "\nlogin expired: run codex login\n"
    _install(monkeypatch, FakeRun(message=None, returncode=3, stderr=stderr))
    with pytest.raises(CodexError) as raised:
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    message = str(raised.value)
    assert "login expired: run codex login" in message
    assert "exited 3" in message
    assert "FIRST-LINE-NOISE" not in message


def test_run_codex_nonzero_exit_ignores_a_message_the_run_left_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeRun(message="partial", returncode=1, stderr="boom"))
    with pytest.raises(CodexError, match="boom"):
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")


@pytest.mark.parametrize("message", [None, "", "  \n\t\n"])
def test_run_codex_empty_last_message_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str | None
) -> None:
    _install(monkeypatch, FakeRun(message=message))
    with pytest.raises(CodexError, match="no last message"):
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")


def test_run_codex_never_returns_a_stale_message_from_an_earlier_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    last = tmp_path / "last.md"
    last.write_text("stale answer from yesterday", "utf-8")
    _install(monkeypatch, FakeRun(message=None))  # exits 0 and writes nothing
    with pytest.raises(CodexError, match="no last message"):
        run_codex("p", [], cwd=tmp_path, last_message=last)


def test_run_codex_turns_a_binary_that_cannot_start_into_a_codex_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeRun(raises=FileNotFoundError("no such file")))
    with pytest.raises(CodexError, match="could not start"):
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")


def test_run_codex_turns_a_timeout_into_a_codex_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeRun(raises=subprocess.TimeoutExpired(["codex"], 7)))
    with pytest.raises(CodexError, match="timed out after 7s"):
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md", timeout_s=7)


def test_run_codex_resolves_a_relative_last_message_once_for_cleanup_argv_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    ours.mkdir()
    theirs.mkdir()
    monkeypatch.chdir(ours)
    fake = _install(monkeypatch, FakeRun(message="from the right file"))

    answer = run_codex("p", [], cwd=theirs, last_message=Path("out/last.md"))

    assert answer == "from the right file"
    cmd = cast("list[str]", fake.calls[0]["cmd"])
    passed = Path(cmd[cmd.index("-o") + 1])
    assert passed.is_absolute()
    assert passed.resolve() == (ours / "out" / "last.md").resolve()
    assert not (theirs / "out").exists()  # Codex wrote where we read, not under its own cwd


def test_run_codex_creates_the_missing_folder_of_the_last_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Codex exits 0 and writes nothing when the `-o` folder is missing, so `run_codex` makes it.
    _install(monkeypatch, FakeRun(message="the answer"))
    last = tmp_path / "a" / "b" / "last.md"
    assert not last.parent.exists()
    assert run_codex("p", [], cwd=tmp_path, last_message=last) == "the answer"
    assert last.read_text("utf-8") == "the answer"


def test_the_fake_leaves_a_missing_last_message_folder_missing(tmp_path: Path) -> None:
    # Guards the fake itself: it must not be kinder than Codex, or the test above proves nothing.
    last = tmp_path / "missing" / "last.md"
    FakeRun(message="x")(["codex", "-o", str(last)], cwd=tmp_path)
    assert not last.parent.exists()


def test_run_codex_refuses_to_start_when_an_image_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `codex exec -i ./missing.png` exits 0 and tells the model the file is missing, so the
    # critic would judge pictures it never saw. Every image is checked before launching.
    fake = _install(monkeypatch, FakeRun())
    good = _image(tmp_path)
    gone_a = tmp_path / "gone-a.png"
    gone_b = tmp_path / "sub" / "gone-b.png"
    with pytest.raises(CodexError) as raised:
        run_codex("p", [gone_a, good, gone_b], cwd=tmp_path, last_message=tmp_path / "last.md")
    message = str(raised.value)
    assert str(gone_a) in message and str(gone_b) in message
    assert str(good) not in message
    assert fake.sequence == []  # neither the login check nor Codex was started


def test_run_codex_refuses_a_directory_in_place_of_an_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch, FakeRun())
    folder = tmp_path / "view.png"
    folder.mkdir()
    with pytest.raises(CodexError, match="view.png"):
        run_codex("p", [folder], cwd=tmp_path, last_message=tmp_path / "last.md")
    assert fake.calls == []


def test_run_codex_hands_codex_absolute_image_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Codex resolves `-i` against its own cwd; the existence check resolves against ours. One
    # absolute path makes both name the same file.
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    ours.mkdir()
    theirs.mkdir()
    _image(ours, "a.png")
    monkeypatch.chdir(ours)
    fake = _install(monkeypatch, FakeRun())

    run_codex("p", [Path("a.png")], cwd=theirs, last_message=tmp_path / "last.md")

    cmd = cast("list[str]", fake.calls[0]["cmd"])
    passed = Path(cmd[cmd.index("-i") + 1])
    assert passed.is_absolute() and passed.resolve() == (ours / "a.png").resolve()


# --- the login preflight ---------------------------------------------------------------------


def test_run_codex_checks_the_login_with_the_same_binary_and_env_before_the_exec_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
    fake = _install(monkeypatch, FakeRun())
    work = tmp_path / "work"
    work.mkdir()

    run_codex("p", [], cwd=work, last_message=tmp_path / "last.md")

    assert fake.sequence == ["status", "exec"]
    (status,) = fake.status_calls
    (execution,) = fake.calls
    assert status["cmd"] == [str(FAKE_BINARY), "login", "status"]
    assert cast("list[str]", execution["cmd"])[0] == str(FAKE_BINARY)
    assert status["env"] == execution["env"]
    assert "OPENAI_API_KEY" not in cast("dict[str, str]", status["env"])
    assert "CODEX_API_KEY" not in cast("dict[str, str]", status["env"])
    assert status["stdin_devnull"] is True and status["cwd"] == work
    timeout = status["timeout_s"]
    assert isinstance(timeout, int) and 0 < timeout <= 120


@pytest.mark.parametrize(
    "stdout, stderr",
    [
        ("", "Logged in using ChatGPT\n"),  # where the CLI prints it today
        ("Logged in using ChatGPT\n", ""),
        ("", "  logged in using chatgpt  \n"),
        ("", "Logged in using ChatGPT\n\n"),
    ],
)
def test_run_codex_proceeds_only_on_a_chatgpt_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str
) -> None:
    fake = _install(monkeypatch, FakeRun(status_stdout=stdout, status_stderr=stderr))
    assert run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md") == "ok"
    assert len(fake.calls) == 1


# A JWT-shaped string, built at run time so no token-like literal sits in the source (the
# pre-push secret scan flags one even when it is a made-up value).
FAKE_JWT = ".".join(
    ("ey" + "JhbGciOiJIUzI1NiJ9", "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0", "abcdefghijklmnop")
)
API_KEY_STATUS = (
    "API key configured - sk-proj-***bcdef\nAuthentication is checked when you send a request.\n"
)


@pytest.mark.parametrize(
    "stdout, stderr, code, mode",
    [
        ("", API_KEY_STATUS, 0, "API key"),  # exit 0: the code alone proves nothing
        ("", "Logged in using an API key - sk-proj-***bcdef\n", 0, "API key"),
        (API_KEY_STATUS, "", 0, "API key"),
        ("", "Logged in using ChatGPT\n" + API_KEY_STATUS, 0, "API key"),
        ("", "Not logged in\n", 1, "not logged in"),
        ("", "Not logged in\n", 0, "not logged in"),
        ("", "", 0, "no output"),
        ("", "", 1, "no output"),
        ("", "   \n\n", 0, "no output"),
        ("", "Logged in using ChatGPT\n", 1, "exit 1"),  # a nonzero exit refuses, whatever it says
        ("", "Something new and unexpected\n", 0, "unrecognized"),
        ("", "Logged in using a company token\n", 0, "unrecognized"),
    ],
)
def test_run_codex_refuses_any_login_that_is_not_chatgpt_and_never_runs_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    stderr: str,
    code: int,
    mode: str,
) -> None:
    fake = _install(
        monkeypatch, FakeRun(status_stdout=stdout, status_stderr=stderr, status_code=code)
    )
    with pytest.raises(CodexError) as raised:
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    message = str(raised.value)
    assert "ChatGPT login" in message
    assert mode.lower() in message.lower()
    assert fake.calls == [] and fake.sequence == ["status"]  # no exec call was made
    assert not (tmp_path / "last.md").exists()


@pytest.mark.parametrize(
    "status, secret",
    [
        (API_KEY_STATUS, "bcdef"),
        (API_KEY_STATUS, "sk-proj"),
        ("Logged in with sk-live-ABCDEF0123456789abcdef0123\n", "ABCDEF0123456789abcdef0123"),
        ("Logged in with sk-live-ABCDEF0123456789abcdef0123\n", "sk-live"),
        pytest.param(f"Token {FAKE_JWT}\n", FAKE_JWT.split(".")[0], id="jwt-shaped"),
        ("key=abcd1234abcd1234abcd1234\n", "abcd1234abcd1234abcd1234"),
        ("Odd mode ****wxyz\n", "wxyz"),
        ("Odd mode sk-***wxyz\n", "wxyz"),
    ],
)
def test_the_login_refusal_never_echoes_a_key_or_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, secret: str
) -> None:
    _install(monkeypatch, FakeRun(status_stderr=status))
    with pytest.raises(CodexError) as raised:
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    assert secret not in str(raised.value)


def test_the_login_refusal_shows_a_short_redacted_line_for_an_unknown_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeRun(status_stderr="Logged in using SSO via example.org\n"))
    with pytest.raises(CodexError, match="Logged in using SSO via example.org"):
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    long_line = "Mode " + "word " * 100
    _install(monkeypatch, FakeRun(status_stderr=long_line))
    with pytest.raises(CodexError) as raised:
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    assert len(str(raised.value)) < 400


@pytest.mark.parametrize(
    "raises",
    [OSError("no such file"), subprocess.TimeoutExpired(["codex", "login", "status"], 60)],
)
def test_run_codex_refuses_when_the_login_check_itself_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raises: BaseException
) -> None:
    fake = _install(monkeypatch, FakeRun(status_raises=raises))
    with pytest.raises(CodexError, match="could not check the codex login"):
        run_codex("p", [], cwd=tmp_path, last_message=tmp_path / "last.md")
    assert fake.calls == []


# --- the order of the attached images is part of the prompt contract ------------------------


def _dash_i_values(cmd: object) -> list[str]:
    argv = cast("list[str]", cmd)
    return [argv[index + 1] for index, token in enumerate(argv) if token == "-i"]


def test_run_codex_keeps_the_image_order_exactly_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch, FakeRun())
    c, a, b = (_image(tmp_path, name) for name in ("c.png", "a.png", "b.png"))

    run_codex("p", [c, a, b], cwd=tmp_path, last_message=tmp_path / "last.md")

    assert _dash_i_values(fake.calls[0]["cmd"]) == [str(c), str(a), str(b)]


def test_run_codex_keeps_a_repeated_image_where_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch, FakeRun())
    b, a = _image(tmp_path, "b.png"), _image(tmp_path, "a.png")

    run_codex("p", [b, a, b], cwd=tmp_path, last_message=tmp_path / "last.md")

    assert _dash_i_values(fake.calls[0]["cmd"]) == [str(b), str(a), str(b)]


def test_explicit_model_and_effort_precede_prompt():
    argv = build_argv(
        Path("/bin/codex"),
        "judge",
        Path("/tmp/last.md"),
        [],
        model="gpt-6-astra",
        reasoning_effort="high",
    )
    assert argv[argv.index("--model") + 1] == "gpt-6-astra"
    assert argv.index("--model") < argv.index("judge")
    assert 'model_reasoning_effort="high"' in argv
