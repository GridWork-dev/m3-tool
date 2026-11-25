"""Run the Codex CLI on the user's subscription, for view synthesis and the vision critic.

Facts about the CLI, each verified in this project, that shape the code below:

- Codex finds its helper binary next to `argv[0]`, so a bare symlink breaks tool execution
  without an error. `codex_binary` resolves the real file.
- `-i` takes any number of values, so a prompt written after it is swallowed as an image path.
  `build_argv` puts the prompt before every `-i`.
- Codex waits on an inherited stdin, so `run_codex` closes it.
- Stdout carries headers, so the answer is read from the `-o` file.
- The ChatGPT login is what is billed, and an API key would bill the API with no ledger row.
  Three guards: `child_env` drops the key and token variables from the child's environment
  (`codex exec` uses `CODEX_API_KEY` instead of the login); `run_codex` runs `codex login status`
  first and refuses anything but a ChatGPT login, because Codex also reuses an API key cached in
  `auth.json` or the OS credential store, which no variable removal touches; and the argv forces
  `forced_login_method="chatgpt"`, so Codex itself refuses API-key credentials at exec time.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from m3_pipeline.stages.lib.proc import run_process

Sandbox = Literal["read-only", "workspace-write"]

# Tests replace this to avoid starting Codex.
_run = run_process

_BINARY_ENV = "M3_CODEX_BIN"
# Variables that would flip Codex from the subscription login to API billing (AGENTS.md). The
# last two are Codex's own overrides: `codex exec` uses `CODEX_API_KEY` in place of the login.
_DROPPED_ENV = frozenset(
    {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"}
)
_STDERR_TAIL_CHARS = 2000
_STATUS_TIMEOUT_S = 60
_CHATGPT_STATUS = "logged in using chatgpt"
# Codex's own refusal of API-key credentials at exec time (verified on codex-cli 0.167.0: exit 1,
# no request sent, no last message written).
_FORCE_CHATGPT = ("-c", 'forced_login_method="chatgpt"')
# Text that looks like a key, a token or a masked fragment of one, for the login refusal.
_SECRETISH = re.compile(r"\S*\*{2,}\S*|\b[A-Za-z]{2,4}-[\w.*-]{4,}|\S{20,}|\S*[=:]\S{12,}")
_LOGIN_LINE_CHARS = 80


class CodexError(RuntimeError):
    """Codex could not be found or started, timed out, exited nonzero or wrote no answer."""


def codex_binary(env: Mapping[str, str] | None = None) -> Path:
    """The real Codex binary: `M3_CODEX_BIN` if set, else `codex` on PATH, symlinks resolved.

    `os.path.realpath` is the same as `readlink -f`. `env` defaults to the process environment.
    Raises CodexError when no override is set and PATH has no `codex`.
    """
    source = os.environ if env is None else env
    override = source.get(_BINARY_ENV, "")
    if override:
        return Path(os.path.realpath(override))
    found = shutil.which("codex", path=source.get("PATH", os.defpath))
    if found is None:
        raise CodexError(f"codex is not on PATH; install it or set {_BINARY_ENV} to its path")
    return Path(os.path.realpath(found))


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of the environment for the Codex child, without `OPENAI_API_KEY`,
    `ANTHROPIC_API_KEY`, `CODEX_API_KEY` and `CODEX_ACCESS_TOKEN`, so the CLI keeps using the
    ChatGPT login. `base` defaults to ours."""
    source = os.environ if base is None else base
    return {key: value for key, value in source.items() if key not in _DROPPED_ENV}


def build_argv(
    binary: Path,
    prompt: str,
    last_message: Path,
    images: Sequence[Path],
    *,
    sandbox: Sandbox = "workspace-write",
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> list[str]:
    """The command line: the prompt comes BEFORE every `-i`, because `-i` is variadic.

    `sandbox` is `workspace-write` by default, for runs that write files (view synthesis). A
    read-only job, like the critic, passes `read-only`. `-c forced_login_method="chatgpt"` makes
    Codex refuse API-key credentials itself.
    """
    argv = [
        str(binary),
        "exec",
        "-s",
        sandbox,
        "--ephemeral",
        "--skip-git-repo-check",
        "-o",
        str(last_message),
        *_FORCE_CHATGPT,
        prompt,
    ]
    # Explicit routing is optional for ordinary synthesis, mandatory at the critic caller.
    prompt_index = argv.index(prompt)
    routing: list[str] = []
    if model is not None:
        routing += ["--model", model]
    if reasoning_effort is not None:
        routing += ["-c", f'model_reasoning_effort="{reasoning_effort}"']
    argv[prompt_index:prompt_index] = routing
    for image in images:
        argv += ["-i", str(image)]
    return argv


def _redacted(line: str) -> str:
    """`line` shortened, with anything that looks like a key or token replaced."""
    return _SECRETISH.sub("[redacted]", line[:200]).strip()[:_LOGIN_LINE_CHARS]


def _login_mode(proc: subprocess.CompletedProcess[str]) -> str:
    """Name the login mode `codex login status` reported, without echoing secret text.

    The CLI prints its status on stderr (stdout is empty), and `API key configured - sk-...` with
    exit 0, so both streams and the text are read, not the exit code alone. Known modes get a
    fixed label; an unknown line is shown redacted and shortened.
    """
    lines = [line.strip() for line in (proc.stderr + "\n" + proc.stdout).splitlines()]
    lines = [line for line in lines if line]
    lowered = [line.lower() for line in lines]
    if not lines:
        return "no output"
    if any("api key" in line for line in lowered):
        return "API key"
    if any(line.startswith("not logged in") for line in lowered):
        return "not logged in"
    if any(line.startswith(_CHATGPT_STATUS) for line in lowered):
        return "ChatGPT"
    return f"unrecognized: {_redacted(lines[0])}"


def _require_chatgpt_login(binary: Path, cwd: Path, env: Mapping[str, str]) -> None:
    """Raise CodexError unless `codex login status` reports a ChatGPT login (exit 0).

    Dropping `OPENAI_API_KEY` and the like from the child's environment is not enough: Codex
    reuses an API key cached in `auth.json` or the OS credential store, and a run on it would
    bill the API with no ledger row. So `run_codex` asks before any inference, with the same
    binary and the same environment as the run, and fails closed: an API key, no login, no
    output, a nonzero exit or a check that cannot run all refuse.
    """
    try:
        proc = _run(
            [str(binary), "login", "status"],
            cwd=cwd,
            timeout_s=_STATUS_TIMEOUT_S,
            stdin_devnull=True,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        raise CodexError(
            f"could not check the codex login: `codex login status` timed out after "
            f"{_STATUS_TIMEOUT_S}s"
        ) from error
    except OSError as error:
        raise CodexError(f"could not check the codex login: {error}") from error
    mode = _login_mode(proc)
    if proc.returncode != 0 or mode != "ChatGPT":
        raise CodexError(
            f"codex is not using the ChatGPT login (login mode: {mode}; `codex login status` "
            f"exit {proc.returncode}); run `codex login` with the ChatGPT account. No Codex run "
            "was started: only the ChatGPT login is allowed, since an API key bills the API "
            "with no ledger row"
        )


def run_codex(
    prompt: str,
    images: Sequence[Path],
    *,
    cwd: Path,
    last_message: Path,
    timeout_s: int = 900,
    sandbox: Sandbox = "workspace-write",
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Run one `codex exec` in `cwd` and return the text of its last message, stripped.

    Relative `images` and `last_message` paths are made absolute against our working directory,
    not `cwd`. Every image must be an existing file, or CodexError is raised before Codex starts.
    `images` keep the order given (the prompt promises it). Before any inference, `codex login
    status` must report a ChatGPT login (see `_require_chatgpt_login`); no other login runs.
    Codex writes its message to `last_message` (`-o`) only if the folder exists, so the folder
    is created, and a file left there by an earlier run is removed first, so a run that writes
    nothing can't return a stale answer. Raises CodexError for every failure: a missing image, a
    login that is not ChatGPT, a binary that can't start, a timeout, a nonzero exit (with the tail
    of stderr) and an empty or missing last message.
    """
    # Codex resolves `-o` and `-i` against `cwd`, we resolve them against our own directory: make
    # every path absolute once, so the checks, the arguments and the read name the same files.
    last_message = last_message.absolute()
    attached = [image.absolute() for image in images]
    # `codex exec -i missing.png` exits 0 and tells the model the file is missing, so the run
    # would go ahead blind and a critic would judge pictures it never saw. Refuse to start.
    missing = [image for image in attached if not image.is_file()]
    if missing:
        names = ", ".join(str(image) for image in missing)
        raise CodexError(f"codex was not started: image file(s) not found: {names}")
    binary = codex_binary()
    env = child_env()
    _require_chatgpt_login(binary, cwd, env)
    argv = build_argv(
        binary,
        prompt,
        last_message,
        attached,
        sandbox=sandbox,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    try:
        last_message.parent.mkdir(parents=True, exist_ok=True)
        last_message.unlink(missing_ok=True)
    except OSError as error:
        raise CodexError(f"could not prepare {last_message}: {error}") from error
    try:
        proc = _run(argv, cwd=cwd, timeout_s=timeout_s, stdin_devnull=True, env=env)
    except subprocess.TimeoutExpired as error:
        raise CodexError(f"codex timed out after {timeout_s}s") from error
    except OSError as error:
        raise CodexError(f"could not start {binary}: {error}") from error
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip() or "no output")[-_STDERR_TAIL_CHARS:]
        raise CodexError(f"codex exited {proc.returncode}: {detail}")
    try:
        text = last_message.read_text("utf-8")
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as error:
        raise CodexError(f"could not read {last_message}: {error}") from error
    if not text.strip():
        raise CodexError(f"codex wrote no last message to {last_message}")
    return text.strip()
