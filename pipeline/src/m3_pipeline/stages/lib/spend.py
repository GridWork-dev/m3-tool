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
5. The rows before it plus the price stay within the cap.
6. The journal has not authorized the tag before: one tag, one call.
7. The reconciled spend, with this call, stays within the cap. Each tag counts once, at the
   highest of its ledger cost, what the journal authorized for it and any cost a recorded
   outcome reports for it; a ledger row without a call tag counts at its cost. The ledger can
   lose a spent row (a bad merge, a tidy-up), the journal can miss spend that only the ledger
   records, and a call can cost more than its estimate, so no one source is trusted alone: two
   independent checks both pass while the sum of the sources passes the cap.

The ledger is prose, then exactly one table that runs to the end of the file. Once the header
row is seen, every non-blank line after it must be a valid table row, or the guard denies and
names the line. That is an allowlist: a row whose frame was lost, swapped for other bars or
prefixed with a bullet cannot be skipped as prose, because no prose may follow the table.

The cap is the smallest of the cap row's cell, the `cap` argument and `SPIKE_CAP_USD`.

The journal lives at a fixed path outside `work_dir`, under the home directory the account
database gives for this user. It never follows an environment variable (`M3_WORK_DIR`, `HOME`),
so changing the environment can never make a spent tag spendable again. The authorization is
journaled (and fsynced) before `authorize` returns, so a crash between authorizing and calling
leaves the tag spent, never free. A journal append that fails midway can leave a torn last line;
that denies every call until a human removes it, which is safe because the failed `authorize`
returned no authorization. A last line that lost only its newline (a crash or a short write) is
read normally and counted; the next append ends it first, so two entries never share a line.

Money is `Decimal` everywhere. A float cannot hold a cent, and its sums drift.
"""

import datetime as dt
import errno
import fcntl
import json
import os
import pwd
import re
from collections.abc import Callable, Generator
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
    """The fixed journal path: `~/.local/state/m3-tool/spend-journal.jsonl` under the home the
    account database lists for this user.

    It never reads `HOME` (`Path.home()` does, so a scrubbed or sandboxed environment would find
    an empty journal and authorize a spent tag again) or `M3_WORK_DIR`. Only `authorize`'s
    `journal` argument overrides it, and only tests pass one.
    """
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        home = ""
    if not os.path.isabs(home):
        raise SpendDenied(
            "the account database has no absolute home directory for this user, so the spend "
            "journal has no fixed path"
        )
    return Path(home) / ".local" / "state" / "m3-tool" / "spend-journal.jsonl"


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
    """The data rows of `docs/spend-ledger.md`: prose, then one table that runs to the end.

    Before the table, lines that do not start with `|` are prose and are ignored. The first
    line that does must be the exact header, so a column that moved cannot be misread silently.
    From the header on there is no prose: every non-blank line must be the separator row and
    then valid data rows, or `SpendDenied` names the line. An allowlist, not a search for
    row-shaped lines, because a row that lost its frame, swapped its bars or gained a bullet
    would otherwise be skipped and its cost left out of the cap. Any malformed row is denied
    too: a row the guard cannot read is a row it cannot count.
    """
    rows: list[LedgerRow] = []
    expecting = "header"
    for number, line in enumerate(text.splitlines(), start=1):
        framed = line.strip().startswith("|")
        if expecting == "header":
            if not framed:
                continue
            if tuple(_cells(number, line)) != _HEADER:
                raise _bad(number, f"expected the table header {' | '.join(_HEADER)!r}")
            expecting = "separator"
            continue
        if not line.strip():
            continue
        if expecting == "separator":
            cells = _cells(number, line) if framed else []
            if len(cells) != len(_HEADER) or not all(_SEPARATOR_CELL.fullmatch(c) for c in cells):
                raise _bad(number, "expected the table separator row (---) under the header")
            expecting = "rows"
        elif framed:
            rows.append(_row(number, _cells(number, line)))
        else:
            raise _bad(
                number,
                "this line is not a table row: the ledger is prose, then one table that runs "
                "to the end of the file, so nothing but table rows may follow its header",
            )
    return rows


def _approve(
    rows: list[LedgerRow],
    tag: str,
    price: Decimal,
    session: str,
    today: dt.date,
    cap: Decimal,
) -> tuple[LedgerRow, Decimal]:
    """Checks 1 to 5, which need only the ledger. Returns the row that authorizes the call and
    the cap that applies, for the journal checks that follow."""
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
    return row, limit


def _reconciled_spend(
    rows: list[LedgerRow], authorized: dict[str, Decimal], outcomes: dict[str, Decimal]
) -> Decimal:
    """What has been spent, counting each tag once at the highest of its ledger cost (all of its
    rows added), its authorized journal price and its highest recorded outcome cost, a missing
    source being zero. A row without a call tag has no journal counterpart and counts at its
    cost.

    Adding the sources would count every spent tag twice, and checking them separately lets
    spend recorded in only one of them hide behind the others.
    """
    spent = Decimal(0)
    ledger_by_tag: dict[str, Decimal] = {}
    for row in rows:
        tag = call_tag(row.purpose)
        if tag is None:
            spent += row.cost
        else:
            ledger_by_tag[tag] = ledger_by_tag.get(tag, Decimal(0)) + row.cost
    for tag in ledger_by_tag.keys() | authorized.keys() | outcomes.keys():
        spent += max(
            ledger_by_tag.get(tag, Decimal(0)),
            authorized.get(tag, Decimal(0)),
            outcomes.get(tag, Decimal(0)),
        )
    return spent


def _read(path: Path, what: str) -> str:
    try:
        return path.read_text("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SpendDenied(f"could not read the {what} at {path}: {error}") from error


@dataclass(frozen=True)
class _Journal:
    tags: set[str]  # every tag any entry names, outcomes included
    authorized: dict[str, Decimal]  # prices authorized per tag (summed if a tag has several)
    outcomes: dict[str, Decimal]  # highest cost any recorded outcome reports per tag


def _read_journal(journal: Path) -> _Journal:
    """What the journal says about each tag: that it was mentioned, the price authorized for it
    and the highest cost an outcome recorded for it. A failed call's price stays: the guard
    cannot tell a failed call that cost nothing from one that was billed. Outcome costs are
    maxed, not added, because a later outcome corrects an earlier report of the same call.

    A line that is not a JSON object with a string `tag`, an authorization without a valid
    string `price`, or an entry whose `cost` is neither absent, null nor a plain decimal amount
    string denies everything: a torn or edited line must not hide a spent tag or price.
    """
    found = _Journal(set(), {}, {})
    if not journal.exists():
        return found
    for number, line in enumerate(_read(journal, "spend journal").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise SpendDenied(f"{journal} line {number} is not valid JSON: repair it") from error
        fields = cast(dict[str, object], entry) if isinstance(entry, dict) else {}
        tag = fields.get("tag")
        if not isinstance(tag, str):
            raise SpendDenied(f"{journal} line {number} has no string 'tag': repair it")
        found.tags.add(tag)
        if fields.get("status") == "authorized":
            price = fields.get("price")
            if not isinstance(price, str) or not _COST.fullmatch(price):
                raise SpendDenied(
                    f"{journal} line {number} is an authorization without a valid string "
                    "'price': repair it"
                )
            found.authorized[tag] = found.authorized.get(tag, Decimal(0)) + Decimal(price)
        cost = fields.get("cost")
        if cost is not None:
            if not isinstance(cost, str) or not _COST.fullmatch(cost):
                raise SpendDenied(
                    f"{journal} line {number} has a 'cost' that is not a plain decimal amount "
                    "string: repair it"
                )
            found.outcomes[tag] = max(found.outcomes.get(tag, Decimal(0)), Decimal(cost))
    return found


def _json_default(value: object) -> str:
    # Money goes into the journal as a string: JSON has no Decimal, and a float loses cents.
    # Fixed-point, because `str(Decimal("20.00").normalize())` is "2E+1", which the journal
    # reader rejects.
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


# Tests replace this to simulate a short write (a full disk).
_write: Callable[[int, bytes], int] = os.write


def _append(journal: Path, entry: dict[str, object]) -> None:
    """Append one JSONL line and fsync it, and the directory, before returning.

    `os.write` may write fewer bytes than asked (a full disk), so it loops until every byte is
    written and raises `OSError` if the writer makes no progress. A caller never gets a success
    for a truncated entry.

    If the journal's last byte is not a newline (an earlier append was cut short), the newline
    goes first, in the same write as the entry. Without it the new entry would be glued to the
    old one, corrupting both lines. Ending a torn line does not make it readable: `authorize`
    still denies on a line that is not valid JSON.
    """
    data = (json.dumps(entry, default=_json_default) + "\n").encode("utf-8")
    fd = os.open(journal, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        size = os.fstat(fd).st_size
        if size > 0 and os.pread(fd, 1, size - 1) != b"\n":
            data = b"\n" + data
        written = 0
        while written < len(data):
            count = _write(fd, data[written:])
            if count <= 0:
                raise OSError(
                    errno.EIO, f"incomplete write to {journal}: {written} of {len(data)} bytes"
                )
            written += count
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
            row, limit = _approve(rows, tag, price, session, today, cap)
            found = _read_journal(journal)
            if tag in found.tags:
                raise SpendDenied(
                    f"tag {tag!r} is already authorized in {journal}: one tag authorizes one "
                    "call, so add a new row with a new tag"
                )
            spent = _reconciled_spend(rows, {**found.authorized, tag: price}, found.outcomes)
            if spent > limit:
                raise SpendDenied(
                    f"spend would reach {spent} against the {limit:.2f} cap (each tag counts "
                    "once, at the highest of its ledger cost, its journal price and its "
                    "recorded outcome cost)"
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

    `cost` is what the guard reads back: the call is then counted at the highest of its ledger
    cost, its authorized price and this cost. It must be a finite, unsigned, non-negative
    `Decimal` (or `None` when unknown), so a float or a malformed amount never reaches the
    journal, where it would deny every later call. "Unsigned" matters: `Decimal("-0")` and
    `Decimal("-0.00")` are not below zero, yet they are journaled as `-0` and `-0.00`, which the
    journal reader rejects.
    """
    cost = fields.get("cost")
    if cost is not None:
        if not isinstance(cost, Decimal):
            raise TypeError(f"cost must be a Decimal or None, not {type(cost).__name__}")
        if not cost.is_finite() or cost < 0 or cost.is_signed():
            raise ValueError(f"cost {cost} must be a finite, unsigned, non-negative amount")
    entry: dict[str, object] = {
        **fields,
        "tag": tag,
        "at": dt.datetime.now(dt.UTC).isoformat(),
    }
    with _locked(journal):
        _append(journal, entry)
