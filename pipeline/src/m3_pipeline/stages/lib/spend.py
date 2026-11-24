"""The spend guard: refuse a paid call that has no session-approved cap and no ledger row.

`authorize` is the only way into a paid call. It reads `docs/spend-ledger.md` and the spend
journal under one exclusive file lock, and it denies (raises `SpendDenied`) unless every rule
below holds. A bug here costs real money, so every check fails closed: a ledger or journal line
it cannot parse denies everything until a human fixes the line.

Rules, checked in this order:

1. `M3_SPEND_SESSION` names this session, and today's ledger has a cap row carrying that
   `session:<label>`. An earlier day's approval, or another session's, covers nothing.
2. Exactly one ledger row carries the call's tag, and it is dated today.
3. That row's cost covers the price.
4. Its running-total cell equals the total recomputed from the rows (catches hand-math errors).
5. The rows before it plus the price stay within the cap, and so does the sum of every row.
6. The journal has not authorized the tag before: one tag, one call.

The cap is the smallest of the cap row's cell, the `cap` argument and `SPIKE_CAP_USD`.

The journal lives at a fixed path outside `work_dir`, so deleting the work directory can never
make a spent tag spendable again. The authorization is journaled (and fsynced) before `authorize`
returns, so a crash between authorizing and calling leaves the tag spent, never free.

Money is `Decimal` everywhere. A float cannot hold a cent, and its sums drift.
"""

import datetime as dt
import fcntl
import json
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

SPIKE_CAP_USD: Decimal = Decimal("50.00")

SESSION_ENV = "M3_SPEND_SESSION"

_HEADER = (
    "Date",
    "Session cap",
    "Service",
    "Purpose",
    "Units",
    "Cost (USD)",
    "Running total / cap",
)
_DASH = "—"
# `[0-9]`, not `\d`: `\d` matches digits of other scripts, which `Decimal` would accept.
_AMOUNT = r"[0-9]+(?:\.[0-9]+)?"
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SESSION_CAP = re.compile(rf"\$({_AMOUNT})(?:\s+\(.*\))?")
_COST = re.compile(_AMOUNT)
_RUNNING = re.compile(rf"({_AMOUNT})\s*/\s*{_AMOUNT}")
_SEPARATOR_CELL = re.compile(r":?-{3,}:?")
_CALL_TAG = re.compile(r"spike:([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s.*)?")
_SESSION_LABEL = re.compile(r"cap approved by the user session:([a-z0-9-]+)(?:\s.*)?")


class SpendDenied(Exception):
    """The guard refuses the call. The message names the cause."""


@dataclass(frozen=True)
class LedgerRow:
    line: int
    date: dt.date
    session_cap: Decimal | None
    service: str
    purpose: str
    units: str
    cost: Decimal
    running: Decimal | None


def call_tag(purpose: str) -> str | None:
    """The tag of a call row: `spike:gen-rodin25-01 Rodin 2.5 ...` gives `gen-rodin25-01`."""
    match = _CALL_TAG.fullmatch(purpose)
    return match.group(1) if match else None


def session_label(purpose: str) -> str | None:
    """The session of a cap row: `cap approved by the user session:2026-11-24-a` gives
    `2026-11-24-a`. Only a purpose that starts with the cap phrase counts, so a call row that
    mentions `session:` in its words cannot pose as an approval."""
    match = _SESSION_LABEL.fullmatch(purpose)
    return match.group(1) if match else None


def default_journal() -> Path:
    """The fixed journal path. It never depends on `M3_WORK_DIR`: only `authorize`'s `journal`
    argument overrides it, and only tests pass one."""
    return Path.home() / ".local" / "state" / "m3-tool" / "spend-journal.jsonl"


def _bad(line: int, why: str) -> SpendDenied:
    return SpendDenied(f"ledger line {line}: {why}")


def _cells(line_number: int, line: str) -> list[str]:
    stripped = line.strip()
    if len(stripped) < 2 or not stripped.endswith("|"):
        raise _bad(line_number, "a table row must start and end with '|'")
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _row(line_number: int, cells: list[str]) -> LedgerRow:
    if len(cells) != len(_HEADER):
        raise _bad(line_number, f"expected {len(_HEADER)} cells, got {len(cells)}")
    day, cap_cell, service, purpose, units, cost_cell, running_cell = cells

    if not _DATE.fullmatch(day):
        raise _bad(line_number, f"date {day!r} is not YYYY-MM-DD")
    try:
        parsed_day = dt.date.fromisoformat(day)
    except ValueError:
        raise _bad(line_number, f"date {day!r} is not a real calendar date") from None

    session_cap: Decimal | None = None
    if cap_cell != _DASH:
        cap_match = _SESSION_CAP.fullmatch(cap_cell)
        if not cap_match:
            raise _bad(line_number, f"session cap cell {cap_cell!r} is not '$<amount> (note)' or —")
        session_cap = Decimal(cap_match.group(1))

    if not _COST.fullmatch(cost_cell):
        raise _bad(line_number, f"cost {cost_cell!r} is not a plain non-negative decimal amount")

    running: Decimal | None = None
    if running_cell != _DASH:
        running_match = _RUNNING.fullmatch(running_cell)
        if not running_match:
            raise _bad(line_number, f"running total cell {running_cell!r} is not '<total> / <cap>'")
        running = Decimal(running_match.group(1))

    return LedgerRow(
        line_number, parsed_day, session_cap, service, purpose, units, Decimal(cost_cell), running
    )


def parse_ledger(text: str) -> list[LedgerRow]:
    """The data rows of `docs/spend-ledger.md`.

    The first table line must be the exact header and the second the separator, so a column
    that moved cannot be misread silently. Prose lines are ignored. Any malformed row raises
    `SpendDenied` naming its line, because a row the guard cannot read is a row it cannot count.
    """
    rows: list[LedgerRow] = []
    expecting = "header"
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip().startswith("|"):
            continue
        cells = _cells(number, line)
        if expecting == "header":
            if tuple(cells) != _HEADER:
                raise _bad(number, f"expected the table header {' | '.join(_HEADER)!r}")
            expecting = "separator"
        elif expecting == "separator":
            if len(cells) != len(_HEADER) or not all(_SEPARATOR_CELL.fullmatch(c) for c in cells):
                raise _bad(number, "expected the table separator row (---) under the header")
            expecting = "rows"
        else:
            rows.append(_row(number, cells))
    return rows


def _approve(
    rows: list[LedgerRow],
    tag: str,
    price: Decimal,
    session: str,
    today: dt.date,
    cap: Decimal,
) -> LedgerRow:
    """Checks 1 to 5 over the parsed ledger. Returns the row that authorizes the call."""
    approved_caps = [
        row.session_cap
        for row in rows
        if row.date == today
        and session_label(row.purpose) == session
        and row.session_cap is not None
    ]
    if not approved_caps:
        raise SpendDenied(
            f"no cap approval for session {session!r} dated {today} in the ledger: the user must "
            f"approve a cap this session, and a cap row 'cap approved by the user "
            f"session:{session}' must carry today's date"
        )
    limit = min(*approved_caps, cap, SPIKE_CAP_USD)

    matches = [row for row in rows if call_tag(row.purpose) == tag]
    if not matches:
        raise SpendDenied(f"no ledger row for tag {tag!r}: add 'spike:{tag} <words>' first")
    if len(matches) > 1:
        lines = ", ".join(str(row.line) for row in matches)
        raise SpendDenied(f"{len(matches)} ledger rows carry the tag {tag!r} (lines {lines})")
    (row,) = matches
    if row.date != today:
        raise SpendDenied(
            f"ledger row for tag {tag!r} (line {row.line}) is dated {row.date}, not today ({today})"
        )

    if row.cost < price:
        raise SpendDenied(
            f"ledger row for tag {tag!r} (line {row.line}): cost {row.cost} is below the "
            f"price {price}"
        )

    position = rows.index(row)
    before = sum((earlier.cost for earlier in rows[:position]), Decimal(0))
    through = before + row.cost
    if row.running is None:
        raise SpendDenied(
            f"ledger row for tag {tag!r} (line {row.line}): running total cell is missing, "
            f"expected {through}"
        )
    if row.running != through:
        raise SpendDenied(
            f"ledger row for tag {tag!r} (line {row.line}): running total cell {row.running} "
            f"does not match the recomputed {through}"
        )

    if before + price > limit:
        raise SpendDenied(
            f"{before} already spent plus the price {price} would pass the {limit:.2f} cap"
        )
    total = sum((each.cost for each in rows), Decimal(0))
    if total > limit:
        raise SpendDenied(f"the ledger totals {total}, over the {limit:.2f} cap")
    return row


def _read(path: Path, what: str) -> str:
    try:
        return path.read_text("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SpendDenied(f"could not read the {what} at {path}: {error}") from error


def _journaled_tags(journal: Path) -> set[str]:
    """Every tag the journal mentions, outcomes included. A line that is not a JSON object with
    a string `tag` denies everything: a torn write must not hide a spent tag."""
    if not journal.exists():
        return set()
    tags: set[str] = set()
    for number, line in enumerate(_read(journal, "spend journal").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise SpendDenied(f"{journal} line {number} is not valid JSON: repair it") from error
        tag = cast(dict[str, object], entry).get("tag") if isinstance(entry, dict) else None
        if not isinstance(tag, str):
            raise SpendDenied(f"{journal} line {number} has no string 'tag': repair it")
        tags.add(tag)
    return tags


def _json_default(value: object) -> str:
    # Money goes into the journal as a string: JSON has no Decimal, and a float loses cents.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _append(journal: Path, entry: dict[str, object]) -> None:
    """Append one JSONL line and fsync it, and the directory, before returning."""
    line = json.dumps(entry, default=_json_default) + "\n"
    fd = os.open(journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(journal.parent, os.O_RDONLY)
    try:
        os.fsync(directory)  # a new journal file must survive a crash too
    finally:
        os.close(directory)


@contextmanager
def _locked(journal: Path) -> Generator[None]:
    """Hold an exclusive lock on `<journal>.lock`.

    `flock` locks the open file, so two processes (or threads) that each open the file contend.
    It blocks until the lock is free, and the OS drops it if its holder dies. The lock file is
    separate from the journal so the journal stays append-only.
    """
    journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(journal.with_name(journal.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def authorize(
    tag: str,
    price: Decimal,
    *,
    ledger: Path,
    journal: Path | None = None,
    today: dt.date | None = None,
    session: str | None = None,
    cap: Decimal = SPIKE_CAP_USD,
) -> LedgerRow:
    """Authorize one paid call, or raise `SpendDenied`. See the module docstring for the rules.

    `session` defaults to env `M3_SPEND_SESSION`, `journal` to `default_journal()` and `today`
    to the local date. The lock is held from reading the ledger until the journal entry is
    written, so two callers racing for the last affordable row cannot both pass.
    """
    session = os.environ.get(SESSION_ENV) if session is None else session
    if not session:
        raise SpendDenied(
            f"{SESSION_ENV} is not set: the orchestrator sets it once the user approves"
        )
    if not price.is_finite() or price <= 0:
        raise SpendDenied(f"price {price} is not a positive amount")
    today = dt.date.today() if today is None else today
    journal = default_journal() if journal is None else journal

    try:
        with _locked(journal):
            # Read the ledger inside the lock: the row we check must be the one that exists now.
            rows = parse_ledger(_read(ledger, "ledger"))
            row = _approve(rows, tag, price, session, today, cap)
            if tag in _journaled_tags(journal):
                raise SpendDenied(
                    f"tag {tag!r} is already authorized in {journal}: one tag authorizes one "
                    "call, so add a new row with a new tag"
                )
            entry: dict[str, object] = {
                "tag": tag,
                "price": price,
                "status": "authorized",
                "at": dt.datetime.now(dt.UTC).isoformat(),
            }
            _append(journal, entry)
    except OSError as error:
        raise SpendDenied(f"could not use the spend journal at {journal}: {error}") from error
    return row


def record_outcome(journal: Path, tag: str, **fields: object) -> None:
    """Append what happened to a call (status, real cost, request id) to the journal.

    Append-only: the line is added under the same lock and nothing is rewritten. It does not
    free the tag, because `authorize` counts every entry that names it. `tag` and `at` are set
    here and cannot be overridden by `fields`.
    """
    entry: dict[str, object] = {
        **fields,
        "tag": tag,
        "at": dt.datetime.now(dt.UTC).isoformat(),
    }
    with _locked(journal):
        _append(journal, entry)
