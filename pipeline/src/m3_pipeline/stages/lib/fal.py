"""The guarded fal client: one paid call per authorized tag, and never a network byte before the
spend guard says yes.

What was confirmed on 2026-11-23, from fal's public docs (no paid call):

- Queue API (fal.ai/docs/api-reference/inference-api): host `https://queue.fal.run` (backup host
  `queue.falrun.com`, same key). Submit is `POST https://queue.fal.run/<model id>`, the full id
  with its path, JSON body, header `Authorization: Key <key>`. The reply is `{status,
  request_id, response_url, status_url, cancel_url}`. fal says not to build the status and result
  URLs yourself (they use only the owner and app, not the endpoint path), so this client uses the
  ones the submit reply carries, and only if they are https on a queue host: the key header goes
  nowhere else.
- Status is `GET status_url`: 202 while `IN_QUEUE` or `IN_PROGRESS`, 200 at `COMPLETED`. A failed
  or cancelled request is also `COMPLETED`, with `error` and `error_type` in the body. The result
  is `GET response_url`: 200 with the model's output, 422 when the model rejected the input, 500
  when the model or platform failed, 404 once the result expired (1 hour, or 6 minutes for a
  result of 10 KB or more), so every file is downloaded before `run` returns.
- A request body is at most 64 MiB. The queue retries a temporary runner error up to 10 times
  unless the request carries `X-Fal-No-Retry: 1`; this client sends it, so a tag is one attempt.
- The queue API returns no dollar cost, only (when the model reports them) billable units in the
  `X-Fal-Billable-Units` header. The cost recorded for a call is therefore the price it was
  authorized at, which is what the registry's rules say fal charges.
- Data URIs: fal's CDN page says "Some models also accept data URIs" and that URLs are the format
  that works with every model; it does not name endpoints, and the model pages say only "URL".
  The client sends images as data URIs, as the plan chose, so the first live call (the Rodin fast
  smoke test, $0.10) is the real test. An endpoint that rejects one answers 422, a failed call,
  and the fix is a fal storage upload for that endpoint, never a retry.

The rules this module enforces, in the order `run` applies them:

1. Everything local: the call id is a spend tag, the endpoint and the host country are allowed,
   the inputs fit the generator, the options are priced, the key is set, every file is read and
   the body is built and within fal's cap. A refusal here has spent nothing, so no tag is burned.
2. `authorize` (the spend guard). Any exception from it, not only `SpendDenied`, is a no-go: no
   network byte, no retry. Production code builds the client without `journal` and calls
   `authorize` with the tag, the price and the ledger only.
3. The submit, never retried. A timeout, a transport error or a 5xx leaves the outcome unknown:
   the journal says `outcome-unknown` and the message points at the fal dashboard.
4. Poll, fetch, download everything, then record the outcome with its cost as a `Decimal`.

A failure after payment keeps what is needed to finish without paying again: the journal holds
the request id, the queue URLs and (if a download failed) the result URLs, and `resume` uses them.

The key is read from env `M3_FAL_KEY` only. It is sent in one header, scrubbed from every message,
and never logged or journaled. Nothing here logs a request body.
"""

import base64
import ipaddress
import itertools
import json
import logging
import os
import re
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import NoReturn, cast
from urllib.parse import urlsplit

import httpx

from m3_pipeline.config import Settings
from m3_pipeline.stages.lib.generators import (
    Generator,
    GeneratorRefused,
    check_endpoint_allowed,
    check_inputs,
    check_policy,
    price_usd,
    request_fields,
    with_derived_options,
)
from m3_pipeline.stages.lib.paths import require_outside_repo, require_write_target_outside_repo
from m3_pipeline.stages.lib.spend import SpendDenied, authorize, default_journal, record_outcome

_log = logging.getLogger(__name__)

KEY_ENV = "M3_FAL_KEY"
HOST_COUNTRY_ENV = "M3_HOST_COUNTRY"

QUEUE_BASE = "https://queue.fal.run"
_QUEUE_HOSTS = frozenset({"queue.fal.run", "queue.falrun.com"})
MAX_BODY_BYTES = 64 * 1024 * 1024  # fal rejects a larger request body
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_MAX_RESULT_FILES = 64
_BODY_OVERHEAD = 4096  # JSON keys, the data URI prefix and the option fields around the files

# Result statuses where fal has confirmed the outcome: 422 the model rejected the input, 500 the
# model or platform failed, 499 the request was cancelled, 404 the result expired or never
# existed. These write the terminal `failed` entry. Anything else (408, 429, 502, 503, 504, an
# auth error, "not complete" 400) may pass, so it never writes the entry that stops `resume`.
_TERMINAL_RESULT_STATUSES = frozenset({404, 422, 499, 500})

_SUBMIT_TIMEOUT_S = 300.0  # a body can be tens of MB of base64
_REQUEST_TIMEOUT_S = 60.0
_DOWNLOAD_TIMEOUT_S = 600.0
_MAX_POLL_ERRORS = 5  # consecutive transient failures while polling

_CALL_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")  # the spend tag grammar
_KEY_VALUE = re.compile(r"[\x21-\x7e]+")  # printable ASCII, no space: a legal header value
_EXTENSION = re.compile(r"\.[a-z0-9]{1,8}")
_UNITS = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_FILE_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")

_MESH_TYPES = {
    ".glb": "model/gltf-binary",
    ".obj": "model/obj",
    ".fbx": "application/octet-stream",
    ".stl": "model/stl",
}


class FalError(RuntimeError):
    """A fal call failed, or could not be started or finished. The message never holds the key.

    `resumable` is True exactly when the message tells the caller to call `resume`: the call was
    paid for and fal still has the request or its result, so `resume` finishes it without a new
    submit. Every other error is final for this tag (or never reached the guard), and a caller
    must not guess a new tag from it.
    """

    def __init__(self, message: str, *, resumable: bool = False) -> None:
        super().__init__(message)
        self.resumable = resumable


@dataclass(frozen=True)
class PlannedCall:
    call_id: str  # the spend tag: `spike:<call_id>` in the ledger
    generator: str  # a registry key
    images: tuple[Path, ...]
    slots: tuple[str, ...]  # one name per image; a mesh generator gets mesh and no images
    mesh: Path | None
    options: Mapping[str, object]


@dataclass(frozen=True)
class CallResult:
    call_id: str
    request_id: str
    files: dict[str, Path]  # result key (`model_glb`, `textures.0`) -> the downloaded file
    cost: Decimal  # the price the call was authorized at (fal's queue API returns no dollars)


@dataclass(frozen=True)
class Reply:
    """What a network seam returns: the status, lower-cased headers and the JSON body (or None)."""

    status: int
    headers: Mapping[str, str]
    json: object | None


def reply_from(response: httpx.Response) -> Reply:
    try:
        body: object = response.json()
    except ValueError:
        body = None
    headers = {name.lower(): value for name, value in response.headers.items()}
    return Reply(response.status_code, headers, body)


def _post(url: str, *, headers: Mapping[str, str], content: bytes, timeout_s: float) -> Reply:
    # No redirects: the key header must never follow a redirect to another host.
    with httpx.Client(timeout=timeout_s, follow_redirects=False) as session:
        return reply_from(session.post(url, headers=dict(headers), content=content))


def _get(url: str, *, headers: Mapping[str, str], timeout_s: float) -> Reply:
    with httpx.Client(timeout=timeout_s, follow_redirects=False) as session:
        return reply_from(session.get(url, headers=dict(headers)))


def _open_part(part: Path) -> int:
    """Create `part` exclusively and return its descriptor, never writing through a symlink.

    The name is predictable, so a planted link at it would otherwise be followed: `open("wb")`
    would truncate the link's target (a file in the repo, say) and the rename would then put
    that data in the output. A link is refused; a stale regular file from a crashed run is
    removed; and `O_EXCL | O_NOFOLLOW` makes a link planted in between fail instead of followed.
    """
    try:
        existing = part.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(existing.st_mode):
            raise OSError(f"{part} is a symlink: refusing to write through it")
        part.unlink()
    return os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


def download_with(session: httpx.Client, url: str, dest: Path, *, timeout_s: float) -> None:
    """Stream `url` to `dest` through a `.part` file, renamed only when complete, so a failure
    leaves nothing under the final name. The part file is created exclusively and never through
    a symlink (`_open_part`). Stops at `MAX_DOWNLOAD_BYTES`. No credentials are sent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    created = False
    try:
        with session.stream("GET", url, timeout=timeout_s) as response:
            response.raise_for_status()
            handle = os.fdopen(_open_part(part), "wb")
            created = True
            with handle:
                written = 0
                for chunk in response.iter_bytes(1 << 20):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise OSError(f"{url} is larger than {MAX_DOWNLOAD_BYTES} bytes")
                    handle.write(chunk)
        part.replace(dest)
    except BaseException:
        if created:  # only what this call made: a refused link or a foreign file stays put
            part.unlink(missing_ok=True)
        raise


def _download(url: str, dest: Path, *, timeout_s: float) -> None:
    with httpx.Client(follow_redirects=True) as session:
        download_with(session, url, dest, timeout_s=timeout_s)


# Tests replace this to avoid waiting between polls.
_sleep: Callable[[float], None] = time.sleep


def _scrub(text: str, key: str) -> str:
    """`text` with the key, and each long part of it, replaced: an error body can echo a header."""
    for secret in {key, *key.split(":")}:
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    return text


def _as_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _excerpt(body: object, key: str) -> str:
    """The body as text, cut to 300 characters. The key is scrubbed first, so one that straddles
    the cut cannot leave a readable fragment."""
    if body is None:
        return "(no JSON body)"
    return _scrub(json.dumps(body, default=str), key)[:300]


def _describe(error: BaseException, key: str) -> str:
    """`ClassName: message` for an error with the key scrubbed. Callers keep this text and let
    the exception go, then raise outside their `except` block: a `FalError` raised inside one
    would carry the original, secret-bearing exception as its `__context__`."""
    return _scrub(f"{type(error).__name__}: {error}", key)


def _queue_url(value: object) -> str | None:
    """`value` if it is an https URL on fal's queue host with no credentials, else None."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    ok = (
        parts.scheme == "https"
        and parts.hostname in _QUEUE_HOSTS
        and parts.username is None
        and parts.password is None
        and port in (None, 443)
    )
    return value if ok else None


def _download_url_problem(url: str) -> str | None:
    """Why `url` may not be fetched, or None. Result URLs come from fal's reply, so they are
    checked: https, a named host (no IP literal, no localhost), no embedded credentials."""
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return "is not a URL"
    host = parts.hostname or ""
    if parts.scheme != "https" or not host:
        return "is not an https URL with a host"
    if parts.username is not None or parts.password is not None:
        return "carries credentials"
    if host == "localhost" or host.endswith(".localhost"):
        return "names localhost"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return "is an IP address"


def _data_uri_for_image(path: Path, data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise GeneratorRefused(f"{path} is not a PNG, JPEG or WebP image")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _file_urls(body: Mapping[str, object], result_field: str) -> dict[str, str]:
    """Every file object (a dict with a non-empty `url`) in a result, by its path in the JSON
    (`model_glb`, `model_urls.obj`, `textures.0`), the result field first."""
    found: dict[str, str] = {}

    def add(key: str, url: str) -> None:
        name = _FILE_KEY_UNSAFE.sub("_", key)
        while name in found:
            name += "_"
        found[name] = url

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            node = cast(dict[str, object], value)
            url = node.get("url")
            if isinstance(url, str):
                if url:
                    add(path, url)
                return
            for name, child in node.items():
                walk(child, f"{path}.{name}" if path else name)
        elif isinstance(value, list):
            for index, child in enumerate(cast(list[object], value)):
                walk(child, f"{path}.{index}")

    walk(body, "")
    if result_field in found:
        first = {result_field: found.pop(result_field)}
        return {**first, **found}
    return found


def _extension(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if _EXTENSION.fullmatch(suffix) else ".bin"


@dataclass(frozen=True)
class _Plan:
    gen: Generator
    price: Decimal
    key: str
    content: bytes


class FalClient:
    """Runs one generator call at a time through fal's queue, behind the spend guard.

    `journal` is for tests: production code leaves it out, and the guard then uses its own fixed
    journal path. The ledger is always `settings.repo_root / "docs" / "spend-ledger.md"`.
    `poll_interval_s` and `max_polls` bound the wait (the default is half an hour); a call still
    running after that stays on fal's queue and `resume` picks it up.
    """

    def __init__(
        self,
        settings: Settings,
        registry: Mapping[str, Generator],
        *,
        env: Mapping[str, str] | None = None,
        journal: Path | None = None,
        poll_interval_s: float = 3.0,
        max_polls: int = 600,
    ) -> None:
        if poll_interval_s < 0 or max_polls < 1:
            raise ValueError(
                "poll_interval_s must not be negative and max_polls must be at least 1"
            )
        self._settings = settings
        self._registry = registry
        self._env: Mapping[str, str] = os.environ if env is None else env
        self._journal = journal
        self._poll_interval_s = poll_interval_s
        self._max_polls = max_polls

    # --- the public calls ---

    def run(self, call: PlannedCall, out_dir: Path) -> CallResult:
        """authorize -> submit -> poll -> fetch -> download everything, then record the cost."""
        plan = self._plan(call, out_dir)
        self._authorize(call.call_id, plan.price)
        key = plan.key
        headers = self._headers(key)
        url = f"{QUEUE_BASE}/{plan.gen.endpoint}"
        _log.info("submitting %s to %s for %s", call.call_id, plan.gen.endpoint, plan.price)
        sent: Reply | None = None
        failure = ""
        try:
            sent = _post(
                url,
                headers={**headers, "Content-Type": "application/json", "X-Fal-No-Retry": "1"},
                content=plan.content,
                timeout_s=_SUBMIT_TIMEOUT_S,
            )
        except Exception as error:  # whatever the seam raises: the request may be on the wire
            failure = _describe(error, key)
        if sent is None:
            self._unknown(call.call_id, plan.gen, key, failure, None)
        response = sent
        queue = self._accepted(call.call_id, plan.gen, key, response)
        request_id, status_url, response_url = queue
        self._record(
            call.call_id,
            "submitted",
            key,
            generator=plan.gen.key,
            endpoint=plan.gen.endpoint,
            request_id=request_id,
            status_url=status_url,
            response_url=response_url,
        )
        return self._finish(
            call.call_id, plan.gen, key, plan.price, queue, out_dir, urls=None, resumed=False
        )

    def resume(self, call_id: str, out_dir: Path) -> CallResult:
        """Finish a call from the journal's request id, or its kept result URLs. Never submits."""
        self._check_call_id(call_id)
        require_outside_repo(repo_root=self._settings.repo_root, path=out_dir)
        key = self._key()
        entries = self._entries(call_id, key)
        authorized = [e for e in entries if e.get("status") == "authorized"]
        if not authorized:
            raise _fail(
                key,
                f"the journal has no authorization for {call_id!r}: resume only finishes a call "
                "this client started and the guard authorized",
            )
        price_text = authorized[-1].get("price")
        if not isinstance(price_text, str) or not _UNITS.fullmatch(price_text):
            raise _fail(key, f"the journal's authorization for {call_id!r} has no valid price")
        price = Decimal(price_text)
        done = {e.get("status") for e in entries}
        if "succeeded" in done:
            raise _fail(key, f"call {call_id!r} already succeeded: its files were recorded then")
        if "failed" in done or "submit-rejected" in done:
            raise _fail(
                key,
                f"call {call_id!r} failed: fal produced no result to resume, and a new call "
                "needs a new tag and ledger row",
            )
        submitted = [e for e in entries if e.get("status") == "submitted"]
        if not submitted:
            raise _fail(
                key,
                f"call {call_id!r} has no request id in the journal (the submit outcome is "
                "unknown): look for it in the fal dashboard; never submit again with this tag",
            )
        entry = submitted[-1]
        gen = self._registry.get(str(entry.get("generator")))
        if gen is None or gen.endpoint != entry.get("endpoint"):
            raise GeneratorRefused(
                f"the journaled generator {entry.get('generator')!r} is not in the registry "
                "with the endpoint it was submitted to"
            )
        check_endpoint_allowed(gen.endpoint, self._registry)
        request_id = entry.get("request_id")
        status_url = _queue_url(entry.get("status_url"))
        response_url = _queue_url(entry.get("response_url"))
        if not isinstance(request_id, str) or status_url is None or response_url is None:
            raise _fail(
                key,
                f"the journal's queue URLs for {call_id!r} are not https URLs on queue.fal.run: "
                "not sending the key there",
            )
        kept = [e for e in entries if e.get("status") == "download-failed"]
        urls: dict[str, str] | None = None
        if kept:
            raw = kept[-1].get("result_urls")
            if isinstance(raw, dict):
                urls = {str(k): str(v) for k, v in cast(dict[object, object], raw).items()}
        return self._finish(
            call_id,
            gen,
            key,
            price,
            (request_id, status_url, response_url),
            out_dir,
            urls=urls,
            resumed=True,
        )

    # --- local checks: nothing here spends anything ---

    def _check_call_id(self, call_id: str) -> None:
        if not _CALL_ID.fullmatch(call_id):
            raise GeneratorRefused(
                f"call id {call_id!r} is not a spend tag (lower-case words joined by single "
                "hyphens): it names the ledger row, the journal entry and the files"
            )

    def _key(self) -> str:
        key = self._env.get(KEY_ENV, "").strip()
        if not key:
            raise FalError(
                f"{KEY_ENV} is not set: put the fal key in ~/.config/secrets.env under that name"
            )
        if not _KEY_VALUE.fullmatch(key):
            raise FalError(f"{KEY_ENV} holds characters that cannot go in a header")
        return key

    def _require_outside_repo(self, path: Path) -> None:
        require_outside_repo(repo_root=self._settings.repo_root, path=path)

    def _plan(self, call: PlannedCall, out_dir: Path) -> _Plan:
        self._check_call_id(call.call_id)
        gen = self._registry.get(call.generator)
        if gen is None:
            raise GeneratorRefused(f"unknown generator {call.generator!r}")
        check_endpoint_allowed(gen.endpoint, self._registry)
        check_policy(gen, host_country=self._env.get(HOST_COUNTRY_ENV))
        self._require_outside_repo(out_dir)
        if len(call.images) != len(call.slots):
            raise GeneratorRefused(
                f"{len(call.images)} images but {len(call.slots)} slots: one slot name per image"
            )
        order = check_inputs(gen, slots=call.slots, has_mesh=call.mesh is not None)
        options = with_derived_options(gen, call.options, image_count=len(call.images))
        price = price_usd(gen, options)
        fields = request_fields(gen, options)
        key = self._key()

        body = dict(fields)

        def put(name: str, value: object) -> None:
            if name in body:
                raise GeneratorRefused(f"{gen.key}: the field {name!r} would be set twice")
            body[name] = value

        if call.mesh is not None:
            assert gen.mesh_field is not None  # a mesh generator has one (checked at load)
            put(gen.mesh_field, self._mesh_uri(gen, call.mesh))
        else:
            uris = [self._image_uri(call.images[index]) for index in order]
            if gen.image_field is not None:
                put(gen.image_field, uris)
            else:
                for index, uri in zip(order, uris, strict=True):
                    put(gen.slot_fields[call.slots[index]], uri)
        try:
            content = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except ValueError as error:
            raise GeneratorRefused(f"{gen.key}: the options are not valid JSON: {error}") from error
        if len(content) > MAX_BODY_BYTES:
            raise GeneratorRefused(
                f"the request body is {len(content)} bytes, over fal's {MAX_BODY_BYTES}-byte "
                "(64 MiB) cap: images and meshes go as base64 data URIs, a third larger"
            )
        return _Plan(gen, price, key, content)

    def _readable(self, path: Path) -> None:
        self._require_outside_repo(path)  # a file in the repo is never uploaded to a vendor
        if not path.is_file():
            raise GeneratorRefused(f"{path} is not a file")

    def _check_encoded_fits(self, path: Path, size: int) -> None:
        """Refuse a file whose base64 form cannot fit fal's body cap, before it is read: a 150 MB
        mesh would otherwise be read, encoded and JSON-encoded (about 600 MB) before refusal."""
        encoded = 4 * ((size + 2) // 3)
        if encoded + _BODY_OVERHEAD > MAX_BODY_BYTES:
            raise GeneratorRefused(
                f"{path.name} is {size} bytes, {encoded} once base64-encoded, over fal's "
                f"{MAX_BODY_BYTES}-byte (64 MiB) request body cap"
            )

    def _image_uri(self, path: Path) -> str:
        self._readable(path)
        self._check_encoded_fits(path, path.stat().st_size)
        return _data_uri_for_image(path, path.read_bytes())

    def _mesh_uri(self, gen: Generator, path: Path) -> str:
        self._readable(path)
        mime = _MESH_TYPES.get(path.suffix.lower())
        if mime is None:
            raise GeneratorRefused(f"{path.name} is not a .glb, .obj, .fbx or .stl mesh")
        size = path.stat().st_size
        if size == 0:
            raise GeneratorRefused(f"{path.name} is empty")
        if gen.max_mesh_bytes is not None and size > gen.max_mesh_bytes:
            raise GeneratorRefused(
                f"{path.name} is {size} bytes, over the {gen.max_mesh_bytes} byte limit of "
                f"{gen.key}"
            )
        self._check_encoded_fits(path, size)
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    # --- the guard ---

    def _ledger(self) -> Path:
        return self._settings.repo_root / "docs" / "spend-ledger.md"

    def _authorize(self, tag: str, price: Decimal) -> None:
        """Ask the guard. Any exception is a no-go: no network byte, no retry."""
        try:
            if self._journal is None:
                authorize(tag, price, ledger=self._ledger())
            else:
                authorize(tag, price, ledger=self._ledger(), journal=self._journal)
        except SpendDenied:
            raise
        except Exception as error:
            raise SpendDenied(
                f"the spend guard failed ({type(error).__name__}: {error}), which counts as a "
                "no: nothing was sent"
            ) from error

    # --- the journal ---

    def _journal_path(self) -> Path:
        return default_journal() if self._journal is None else self._journal

    def _record(self, tag: str, status: str, key: str, **fields: object) -> None:
        try:
            record_outcome(self._journal_path(), tag, status=status, **fields)
        except Exception as error:
            request = fields.get("request_id")
            raise _fail(
                key,
                f"call {tag}: could not journal {status!r} ({type(error).__name__}: {error})"
                + (f"; fal request id {request}" if request else ""),
            ) from error

    def _entries(self, tag: str, key: str) -> list[dict[str, object]]:
        path = self._journal_path()
        if not path.exists():
            return []
        try:
            text = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise _fail(key, f"could not read the spend journal at {path}: {error}") from error
        found: list[dict[str, object]] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry: object = json.loads(line)
            except json.JSONDecodeError as error:
                raise _fail(key, f"{path} line {number} is not valid JSON: repair it") from error
            if isinstance(entry, dict) and cast(dict[str, object], entry).get("tag") == tag:
                found.append(cast(dict[str, object], entry))
        return found

    # --- submit ---

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Key {key}"}

    def _unknown(
        self, tag: str, gen: Generator, key: str, cause: str, request_id: str | None
    ) -> NoReturn:
        """Journal `outcome-unknown` and raise: fal may or may not have the request."""
        fields: dict[str, object] = {
            "generator": gen.key,
            "endpoint": gen.endpoint,
            "error": _scrub(cause, key)[:300],
        }
        if request_id is not None:
            fields["request_id"] = request_id
        self._record(tag, "outcome-unknown", key, **fields)
        raise _fail(
            key,
            f"submit of {tag} to {gen.endpoint} ended without a usable answer ({cause}): fal may "
            f"or may not have accepted it. Check the fal dashboard (fal.ai/dashboard) for "
            f"{gen.endpoint} before spending again. The tag is spent and is never retried, and "
            "nothing was sent twice",
        )

    def _accepted(
        self, tag: str, gen: Generator, key: str, response: Reply
    ) -> tuple[str, str, str]:
        """The request id and queue URLs of an accepted submit, or raise."""
        if 400 <= response.status < 500:
            self._record(
                tag,
                "submit-rejected",
                key,
                generator=gen.key,
                endpoint=gen.endpoint,
                http_status=response.status,
                error=_excerpt(response.json, key),
            )
            raise _fail(
                key,
                f"fal rejected the submit of {tag} with HTTP {response.status}: "
                f"{_excerpt(response.json, key)}. The tag is spent; a new call needs a new tag and "
                "ledger row",
            )
        if response.status != 200:
            self._unknown(tag, gen, key, f"HTTP {response.status}", None)
        body = _as_dict(response.json) or {}
        request_id = body.get("request_id") or response.headers.get("x-fal-request-id")
        request = request_id if isinstance(request_id, str) and request_id else None
        status_url = _queue_url(body.get("status_url"))
        response_url = _queue_url(body.get("response_url"))
        if request is None or status_url is None or response_url is None:
            self._unknown(
                tag,
                gen,
                key,
                "the reply has no request id, or its status and result URLs are not https URLs "
                "on queue.fal.run",
                request,
            )
        return request, status_url, response_url

    # --- poll, fetch, download ---

    def _finish(
        self,
        tag: str,
        gen: Generator,
        key: str,
        price: Decimal,
        queue: tuple[str, str, str],
        out_dir: Path,
        *,
        urls: dict[str, str] | None,
        resumed: bool,
    ) -> CallResult:
        request_id, status_url, response_url = queue
        units: str | None = None
        if urls is None:
            self._poll(tag, key, request_id, status_url)
            body, units = self._fetch(tag, gen, key, request_id, response_url)
            urls = _file_urls(body, gen.result_field)
            if gen.result_field not in urls:
                self._record(
                    tag, "failed", key, request_id=request_id, generator=gen.key,
                    error=f"the result has no {gen.result_field!r} file",
                )  # fmt: skip
                raise _fail(
                    key,
                    f"{tag}: fal's result has no {gen.result_field!r} file (it has "
                    f"{', '.join(urls) or 'no files'}); the call was paid for, so check the fal "
                    "dashboard",
                )
            if len(urls) > _MAX_RESULT_FILES:
                # The call was paid for and the result field is first: cut the extras, never
                # the result.
                _log.warning(
                    "%s: the result lists %d files; keeping %d", tag, len(urls), _MAX_RESULT_FILES
                )
                urls = dict(itertools.islice(urls.items(), _MAX_RESULT_FILES))
        files = self._download_all(tag, key, request_id, urls, out_dir)
        fields: dict[str, object] = {
            "request_id": request_id,
            "generator": gen.key,
            "cost": price,
            "files": {name: path.name for name, path in files.items()},
            "resumed": resumed,
        }
        if units is not None and _UNITS.fullmatch(units):
            fields["billable_units"] = units
        self._record(tag, "succeeded", key, **fields)
        _log.info("%s finished: %d file(s)", tag, len(files))
        return CallResult(tag, request_id, files, price)

    def _poll(self, tag: str, key: str, request_id: str, status_url: str) -> None:
        errors = 0
        for attempt in range(self._max_polls):
            if attempt:
                _sleep(self._poll_interval_s)
            response: Reply | None = None
            cause = ""
            try:
                response = _get(
                    status_url, headers=self._headers(key), timeout_s=_REQUEST_TIMEOUT_S
                )
            except (httpx.HTTPError, OSError) as error:
                cause = _describe(error, key)
            if response is None:
                errors += 1
                self._too_many_errors(tag, key, errors, cause)
                continue
            if response.status >= 500 or response.status in (408, 429):
                errors += 1
                self._too_many_errors(tag, key, errors, f"HTTP {response.status}")
                continue
            if response.status >= 400:
                raise _fail(
                    key,
                    f"fal answered HTTP {response.status} while polling {tag} "
                    f"(request {request_id}): {_excerpt(response.json, key)}. Nothing is "
                    f"recorded as failed: resume({tag!r}, out_dir) polls it again without "
                    "submitting",
                    resumable=True,
                )
            errors = 0
            body = _as_dict(response.json) or {}
            _log.debug("%s status %s", tag, body.get("status"))
            if body.get("status") != "COMPLETED":
                continue
            failure = body.get("error")
            if failure:
                detail = _scrub(f"{failure} ({body.get('error_type', 'no error type')})", key)
                self._record(tag, "failed", key, request_id=request_id, error=detail[:300])
                raise _fail(key, f"fal reports {tag} (request {request_id}) failed: {detail}")
            return
        raise _fail(
            key,
            f"{tag} (request {request_id}) is not complete after {self._max_polls} checks. It "
            f"is still on fal's queue: resume({tag!r}, out_dir) polls it again without "
            "submitting",
            resumable=True,
        )

    def _too_many_errors(self, tag: str, key: str, errors: int, cause: str) -> None:
        if errors >= _MAX_POLL_ERRORS:
            raise _fail(
                key,
                f"polling {tag} failed {errors} times in a row ({cause}). The request is still "
                f"on fal's queue: resume({tag!r}, out_dir) polls it again without submitting",
                resumable=True,
            )

    def _fetch(
        self, tag: str, gen: Generator, key: str, request_id: str, response_url: str
    ) -> tuple[dict[str, object], str | None]:
        """The result body. Only a confirmed outcome writes `failed` (see
        `_TERMINAL_RESULT_STATUSES`); a transport error or any other status leaves the call
        resumable, because the request is complete and paid for, and fal keeps the result an
        hour (6 minutes if it is large)."""
        again = (
            f"nothing is recorded as failed: resume({tag!r}, out_dir) fetches the result again "
            "without submitting. fal keeps a result for 1 hour, or 6 minutes if it is large"
        )
        response: Reply | None = None
        cause = ""
        try:
            response = _get(response_url, headers=self._headers(key), timeout_s=_REQUEST_TIMEOUT_S)
        except (httpx.HTTPError, OSError) as error:
            cause = _describe(error, key)
        if response is None:
            raise _fail(
                key, f"could not fetch the result of {tag} ({cause}); {again}", resumable=True
            )
        result = _as_dict(response.json)
        if response.status == 200 and result is not None:
            return result, response.headers.get("x-fal-billable-units")
        detail = f"HTTP {response.status}: {_excerpt(response.json, key)}"
        if response.status in _TERMINAL_RESULT_STATUSES:
            self._record(
                tag, "failed", key, request_id=request_id, generator=gen.key, error=detail[:300]
            )
            raise _fail(key, f"fal returned no result for {tag} (request {request_id}): {detail}")
        raise _fail(
            key,
            f"fal answered {detail} for the result of {tag} (request {request_id}), which may "
            f"pass; {again}",
            resumable=True,
        )

    def _download_all(
        self, tag: str, key: str, request_id: str, urls: Mapping[str, str], out_dir: Path
    ) -> dict[str, Path]:
        """Download every file, the result field first, one download per distinct URL."""
        files: dict[str, Path] = {}
        by_url: dict[str, Path] = {}
        failure: str | None = None
        try:
            for name, url in urls.items():
                problem = _download_url_problem(url)
                if problem:
                    raise OSError(
                        f"the result URL for {name} {problem}: only https hosts are fetched"
                    )
            for name, url in urls.items():
                if url in by_url:
                    files[name] = by_url[url]
                    continue
                dest = out_dir / f"{tag}.{name}{_extension(url)}"
                require_write_target_outside_repo(dest=dest, repo_root=self._settings.repo_root)
                _download(url, dest, timeout_s=_DOWNLOAD_TIMEOUT_S)
                by_url[url] = dest
                files[name] = dest
        except (httpx.HTTPError, OSError, ValueError) as error:
            failure = _describe(error, key)
        if failure is not None:
            self._record(
                tag, "download-failed", key, request_id=request_id, result_urls=dict(urls),
                error=failure[:300],
            )  # fmt: skip
            raise _fail(
                key,
                f"downloading the result of {tag} failed ({failure}). The call was paid for and "
                f"its result URLs are in the journal: resume({tag!r}, out_dir) downloads them "
                "without a new submit. fal keeps a result for 1 hour, or 6 minutes if it is large",
                resumable=True,
            )
        return files


def _fail(key: str, message: str, *, resumable: bool = False) -> FalError:
    return FalError(_scrub(message, key), resumable=resumable)
