"""Tests for the spend guard.

A guard that fails open costs real money, so every denial has its own test, matched on the cause.
Nothing here touches the network or the real journal under `~/.local/state`.
"""

import fcntl
import json
import multiprocessing
import multiprocessing.queues
import multiprocessing.synchronize
import os
import pwd
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import m3_pipeline.stages.lib.spend as spend_mod
from m3_pipeline.config import load_settings
from m3_pipeline.stages.lib.spend import (
    SPIKE_CAP_USD,
    LedgerRow,
    SpendDenied,
    authorize,
    call_tag,
    default_journal,
    parse_ledger,
    record_outcome,
    session_label,
)

TODAY = date(2026, 11, 24)
YESTERDAY = date(2026, 11, 23)
SESSION = "2026-11-24-a"
CAP_CELL = "$50 (Phase 0 spike, 3D generation)"
REAL_LEDGER = load_settings({}).repo_root / "docs" / "spend-ledger.md"
# Read at import, before any test changes $HOME or the account database.
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)

# The preamble is four lines, so the header is line 5, the separator line 6, the first row line 7.
PREAMBLE = "# Spend ledger\n\nProse that is not a table row.\n\n"
HEADER = (
    "| Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap |\n"
    "|---|---|---|---|---|---|---|\n"
)
FIRST_ROW_LINE = 7


@dataclass(frozen=True)
class Spec:
    """One ledger row, as the test wants it. `running` overrides the computed running total."""

    day: date
    purpose: str
    cost: str
    cap_cell: str = CAP_CELL
    running: str | None = None
    service: str = "fal"
    units: str = "1"


def cap_approval(day: date = TODAY, label: str = SESSION, cap_cell: str = CAP_CELL) -> Spec:
    return Spec(day, f"cap approved by the user session:{label}", "0.00", cap_cell, None, "—", "—")


def call(
    tag: str,
    cost: str,
    day: date = TODAY,
    running: str | None = None,
    cap_cell: str = CAP_CELL,
) -> Spec:
    return Spec(day, f"spike:{tag} test generation", cost, cap_cell, running)


def render(*specs: Spec, limit: str = "50.00") -> str:
    """Render the real table header plus rows, computing each running total from the costs."""
    total = Decimal("0")
    lines: list[str] = []
    for spec in specs:
        total += Decimal(spec.cost)
        running = spec.running if spec.running is not None else f"{total:.2f} / {limit}"
        lines.append(
            f"| {spec.day.isoformat()} | {spec.cap_cell} | {spec.service} | {spec.purpose} "
            f"| {spec.units} | {spec.cost} | {running} |\n"
        )
    return PREAMBLE + HEADER + "".join(lines)


def write_ledger(tmp_path: Path, *specs: Spec, limit: str = "50.00") -> Path:
    path = tmp_path / "ledger.md"
    path.write_text(render(*specs, limit=limit), "utf-8")
    return path


def attempt(
    tmp_path: Path,
    *specs: Spec,
    tag: str = "gen-1",
    price: str = "0.40",
    session: str | None = SESSION,
    today: date = TODAY,
    cap: Decimal = SPIKE_CAP_USD,
    limit: str = "50.00",
) -> LedgerRow:
    """Authorize `tag` against a ledger built from `specs`; the journal persists in `tmp_path`."""
    return authorize(
        tag,
        Decimal(price),
        ledger=write_ledger(tmp_path, *specs, limit=limit),
        journal=tmp_path / "j.jsonl",
        today=today,
        session=session,
        cap=cap,
    )


def grant(tag: str, ledger: Path, journal: Path) -> LedgerRow:
    """`authorize` for a 0.40 call, today, in the test session."""
    return authorize(
        tag, Decimal("0.40"), ledger=ledger, journal=journal, today=TODAY, session=SESSION
    )


def journal_entries(journal: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = [
        json.loads(line) for line in journal.read_text().splitlines()
    ]
    return entries


# --- authorize: the accepting path and the cap arithmetic ---


def test_authorize_accepts_a_row_that_covers_the_price(tmp_path: Path) -> None:
    row = attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))
    assert row.cost == Decimal("0.40")
    assert row.purpose.startswith("spike:gen-1 ")


def test_authorize_accepts_a_row_that_lands_exactly_on_the_cap(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("prior-1", "49.60"), call("gen-1", "0.40"))


def test_authorize_accepts_a_row_costing_more_than_the_price(tmp_path: Path) -> None:
    # The estimate may exceed the real price, never undercut it.
    row = attempt(tmp_path, cap_approval(), call("gen-1", "0.50"), price="0.40")
    assert row.cost == Decimal("0.50")


def test_a_row_pushing_the_total_past_the_cap_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match=r"would pass the 50\.00 cap"):
        attempt(
            tmp_path, cap_approval(), call("prior-1", "49.80"), call("gen-9", "0.40"), tag="gen-9"
        )
    assert not (tmp_path / "j.jsonl").exists()


def test_the_hard_cap_wins_over_a_larger_cap_cell(tmp_path: Path) -> None:
    rows = (cap_approval(cap_cell="$80"), call("prior-1", "49.80"), call("gen-9", "0.40"))
    with pytest.raises(SpendDenied, match=r"50\.00"):
        attempt(tmp_path, *rows, tag="gen-9", limit="80.00")


def test_the_hard_cap_wins_over_a_larger_cap_argument(tmp_path: Path) -> None:
    # A caller cannot lift the spike cap by passing a bigger `cap`, even with a $80 cell.
    rows = (cap_approval(cap_cell="$80"), call("prior-1", "49.80"), call("gen-9", "0.40"))
    with pytest.raises(SpendDenied, match=r"would pass the 50\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-9", cap=Decimal("100"), limit="80.00")


def test_a_smaller_cap_argument_wins_over_the_cap_cell(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match=r"would pass the 10\.00 cap"):
        attempt(
            tmp_path,
            cap_approval(),
            call("prior-1", "9.80"),
            call("gen-9", "0.40"),
            tag="gen-9",
            cap=Decimal("10.00"),
        )


def test_a_smaller_cap_cell_wins_over_the_hard_cap(tmp_path: Path) -> None:
    rows = (cap_approval(cap_cell="$20 (smaller)"), call("prior-1", "19.80"), call("gen-9", "0.40"))
    with pytest.raises(SpendDenied, match=r"would pass the 20\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-9", limit="20.00")


def test_total_of_all_rows_over_cap_is_denied_even_if_this_row_fits(tmp_path: Path) -> None:
    # A later row already pushed the ledger past the cap, so nothing more is authorized.
    rows = (cap_approval(), call("gen-1", "0.40"), call("later-1", "60.00"))
    with pytest.raises(SpendDenied, match=r"would reach 60\.40 against the 50\.00 cap"):
        attempt(tmp_path, *rows)


def test_money_is_decimal_never_float(tmp_path: Path) -> None:
    # 0.1 + 0.2 is 0.30000000000000004 as a float; the guard must see exactly 0.30.
    row = attempt(
        tmp_path,
        cap_approval(),
        call("prior-1", "0.10"),
        call("prior-2", "0.20"),
        call("gen-1", "0.30"),
        price="0.30",
    )
    assert isinstance(row.cost, Decimal)
    assert isinstance(row.running, Decimal)
    assert row.running == Decimal("0.60")


# --- authorize: the denials, each with its cause ---


def test_missing_row_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="no ledger row"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), tag="gen-2")


def test_duplicate_tag_rows_are_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="2 ledger rows"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), call("gen-1", "0.40"))


def test_row_cost_below_price_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match=r"cost 0\.40 is below the price 0\.50"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), price="0.50")


def test_no_cap_approval_for_this_session_dated_today_is_denied(tmp_path: Path) -> None:
    # An old approval covers nothing: the only cap row is dated yesterday.
    with pytest.raises(SpendDenied, match="no cap approval"):
        attempt(tmp_path, cap_approval(day=YESTERDAY), call("gen-1", "0.40"))


def test_missing_session_env_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("M3_SPEND_SESSION", raising=False)
    with pytest.raises(SpendDenied, match="M3_SPEND_SESSION"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), session=None)


def test_empty_session_env_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M3_SPEND_SESSION", "")
    with pytest.raises(SpendDenied, match="M3_SPEND_SESSION"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), session=None)


def test_session_defaults_to_the_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M3_SPEND_SESSION", SESSION)
    attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), session=None)


def test_same_date_but_a_different_session_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="no cap approval"):
        attempt(tmp_path, cap_approval(label="2026-11-24-b"), call("gen-1", "0.40"))


def test_a_session_label_that_only_starts_like_ours_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="no cap approval"):
        attempt(tmp_path, cap_approval(label=f"{SESSION}-2"), call("gen-1", "0.40"))


def test_a_cap_row_without_a_cap_amount_approves_nothing(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="no cap approval"):
        attempt(tmp_path, cap_approval(cap_cell="—"), call("gen-1", "0.40"))


def test_a_call_row_cannot_pose_as_a_cap_row(tmp_path: Path) -> None:
    forged = Spec(TODAY, f"spike:gen-0 note session:{SESSION}", "0.00")
    with pytest.raises(SpendDenied, match="no cap approval"):
        attempt(tmp_path, forged, call("gen-1", "0.40"))


def test_row_dated_another_day_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match=r"dated 2026-11-23, not today \(2026-11-24\)"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40", day=YESTERDAY))


def test_running_total_cell_must_match_the_recomputed_sum(tmp_path: Path) -> None:
    # Hand-math error: the cell says 0.50 but the rows sum to 0.40.
    with pytest.raises(SpendDenied, match=r"running total cell 0\.50 .*recomputed 0\.40"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40", running="0.50 / 50.00"))


def test_a_missing_running_total_cell_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="running total cell"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40", running="—"))


@pytest.mark.parametrize("price", ["0", "0.00", "-0.40", "NaN", "Infinity"])
def test_a_price_that_is_not_a_positive_amount_is_denied(tmp_path: Path, price: str) -> None:
    with pytest.raises(SpendDenied, match="price"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), price=price)


def test_the_existing_cap_row_without_a_session_label_parses_and_authorizes_nothing(
    tmp_path: Path,
) -> None:
    text = REAL_LEDGER.read_text("utf-8")
    legacy = next(row for row in parse_ledger(text) if row.purpose == "cap approved by the user")
    assert session_label(legacy.purpose) is None
    assert legacy.session_cap == Decimal("50")

    # Append a call row to the real file and try to authorize it on the legacy row's own date.
    ledger = tmp_path / "ledger.md"
    ledger.write_text(text.rstrip("\n") + "\n" + _call_line(legacy.date) + "\n", "utf-8")
    with pytest.raises(SpendDenied, match="no cap approval"):
        authorize(
            "gen-1",
            Decimal("0.40"),
            ledger=ledger,
            journal=tmp_path / "j.jsonl",
            today=legacy.date,
            session=SESSION,
        )


def _call_line(day: date) -> str:
    return f"| {day.isoformat()} | {CAP_CELL} | fal | spike:gen-1 test | 1 | 0.40 | 0.40 / 50.00 |"


def test_a_ledger_that_cannot_be_read_is_denied(tmp_path: Path) -> None:
    with pytest.raises(SpendDenied, match="could not read the ledger"):
        grant("gen-1", tmp_path / "missing.md", tmp_path / "j.jsonl")


def test_malformed_ledger_row_names_the_line(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, cap_approval(), call("gen-1", "0.40"))
    ledger.write_text(ledger.read_text() + "| 2026-11-24 | $50 | fal | spike:gen-2 x | 1 |\n")
    with pytest.raises(SpendDenied, match=r"line 9: .*7 cells"):
        grant("gen-1", ledger, tmp_path / "j.jsonl")


# --- authorize: one tag, one call; the journal and the lock ---


def test_tag_can_authorize_one_call_only(tmp_path: Path) -> None:
    rows = (cap_approval(), call("gen-1", "0.40"))
    attempt(tmp_path, *rows)
    with pytest.raises(SpendDenied, match="already"):
        attempt(tmp_path, *rows)
    assert len(journal_entries(tmp_path / "j.jsonl")) == 1


def test_a_recorded_outcome_does_not_free_the_tag(tmp_path: Path) -> None:
    rows = (cap_approval(), call("gen-1", "0.40"))
    attempt(tmp_path, *rows)
    record_outcome(tmp_path / "j.jsonl", "gen-1", status="failed")
    with pytest.raises(SpendDenied, match="already"):
        attempt(tmp_path, *rows)


def test_an_outcome_alone_in_the_journal_still_spends_the_tag(tmp_path: Path) -> None:
    record_outcome(tmp_path / "j.jsonl", "gen-1", status="failed")
    with pytest.raises(SpendDenied, match="already"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


def test_the_journal_records_the_authorization(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))
    (entry,) = journal_entries(tmp_path / "j.jsonl")
    assert entry["tag"] == "gen-1"
    assert entry["price"] == "0.40"  # a string: JSON has no Decimal, and a float would lose cents
    assert entry["status"] == "authorized"
    assert isinstance(entry["at"], str)


def test_a_normalized_price_is_journaled_in_fixed_point_and_read_back(tmp_path: Path) -> None:
    # Decimal("20.00").normalize() is Decimal("2E+1"); str() of it would be unreadable to the
    # journal reader and deny everything afterwards.
    normalized = Decimal("20.00").normalize()
    assert str(normalized) == "2E+1"
    ledger = write_ledger(tmp_path, cap_approval(), call("gen-a", "20.00"), call("gen-b", "5.00"))
    journal = tmp_path / "j.jsonl"
    authorize("gen-a", normalized, ledger=ledger, journal=journal, today=TODAY, session=SESSION)

    (entry,) = journal_entries(journal)
    assert entry["price"] == "20"
    grant("gen-b", ledger, journal)  # reads the journal back: it must not be corrupt


def test_record_outcome_writes_decimals_in_fixed_point(tmp_path: Path) -> None:
    journal = tmp_path / "j.jsonl"
    record_outcome(journal, "gen-1", cost=Decimal("1E+1"), tiny=Decimal("1E-7"))
    (entry,) = journal_entries(journal)
    assert (entry["cost"], entry["tiny"]) == ("10", "0.0000001")


def test_authorize_creates_the_journal_directory(tmp_path: Path) -> None:
    journal = tmp_path / "state" / "m3-tool" / "j.jsonl"
    authorize(
        "gen-1",
        Decimal("0.40"),
        ledger=write_ledger(tmp_path, cap_approval(), call("gen-1", "0.40")),
        journal=journal,
        today=TODAY,
        session=SESSION,
    )
    assert journal.is_file()


def test_a_corrupt_journal_denies_everything(tmp_path: Path) -> None:
    (tmp_path / "j.jsonl").write_text('{"tag": "gen-0", "status": "auth\n')
    with pytest.raises(SpendDenied, match=r"j\.jsonl line 1"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


@pytest.mark.parametrize("line", ["[1, 2]", '{"status": "authorized"}', '{"tag": 7}'])
def test_a_journal_entry_without_a_tag_denies_everything(tmp_path: Path, line: str) -> None:
    (tmp_path / "j.jsonl").write_text(line + "\n")
    with pytest.raises(SpendDenied, match=r"j\.jsonl line 1"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


def test_the_journal_total_caps_spend_when_a_spent_row_leaves_the_ledger(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "20.00"), tag="gen-a", price="20.00")
    attempt(
        tmp_path,
        cap_approval(),
        call("gen-a", "20.00"),
        call("gen-b", "25.00"),
        tag="gen-b",
        price="25.00",
    )
    # A bad conflict resolution drops gen-a's row: the ledger now totals 25.00 and gen-c fits
    # it (49.00), but the journal remembers gen-a's 20.00, so spend would reach 69.00.
    with pytest.raises(SpendDenied, match=r"would reach 69\.00 against the 50\.00 cap"):
        attempt(
            tmp_path,
            cap_approval(),
            call("gen-b", "25.00"),
            call("gen-c", "24.00"),
            tag="gen-c",
            price="24.00",
        )
    assert [e["tag"] for e in journal_entries(tmp_path / "j.jsonl")] == ["gen-a", "gen-b"]


def test_authorizations_may_reach_the_cap_exactly(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "20.00"), tag="gen-a", price="20.00")
    rows = (cap_approval(), call("gen-a", "20.00"), call("gen-b", "30.00"))
    attempt(tmp_path, *rows, tag="gen-b", price="30.00")


def test_a_failed_calls_authorized_price_still_counts_toward_the_cap(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "40.00"), tag="gen-a", price="40.00")
    record_outcome(tmp_path / "j.jsonl", "gen-a", status="failed")
    rows = (cap_approval(), call("gen-a", "0.00"), call("gen-b", "11.00"))  # gen-a corrected to 0
    with pytest.raises(SpendDenied, match=r"would reach 51\.00 against the 50\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-b", price="11.00")


def test_ledger_only_spending_and_a_dropped_row_cannot_stack_past_the_cap(tmp_path: Path) -> None:
    # 30.00 of earlier spending lives only in the ledger (no journal entry). gen-a takes the
    # ledger to 50.00 and the journal to 20.00.
    prior = call("prior-1", "30.00")
    attempt(tmp_path, cap_approval(), prior, call("gen-a", "20.00"), tag="gen-a", price="20.00")
    # gen-a's row is then lost. gen-b passes each total on its own (ledger 50.00, journal 40.00),
    # but 30.00 + 20.00 + 20.00 has been spent, so the cap is passed.
    rows = (cap_approval(), prior, call("gen-b", "20.00"))
    with pytest.raises(SpendDenied, match=r"would reach 70\.00 against the 50\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-b", price="20.00")
    assert [e["tag"] for e in journal_entries(tmp_path / "j.jsonl")] == ["gen-a"]


@pytest.mark.parametrize(
    ("authorized", "ledger_now", "next_price", "denial"),
    [
        # Corrected down from 20.00 to 5.00: the journal's higher figure counts, once.
        ("20.00", "5.00", "5.00", None),
        ("20.00", "5.00", "6.00", r"would reach 51\.00 against the 50\.00 cap"),
        # Corrected up from 5.00 to 20.00: the ledger's higher figure counts, once (the
        # ledger-only check sees it first, because the rows before gen-b already hold it).
        ("5.00", "20.00", "5.00", None),
        ("5.00", "20.00", "6.00", r"45\.00 already spent plus the price 6\.00 would pass"),
    ],
)
def test_a_tag_in_both_ledger_and_journal_counts_once_at_the_higher_figure(
    tmp_path: Path, authorized: str, ledger_now: str, next_price: str, denial: str | None
) -> None:
    prior = call("prior-1", "25.00")  # ledger only
    attempt(
        tmp_path, cap_approval(), prior, call("gen-a", authorized), tag="gen-a", price=authorized
    )
    rows = (cap_approval(), prior, call("gen-a", ledger_now), call("gen-b", next_price))
    # Counted once at 20.00: 25.00 + 20.00 + next_price. Summed, or counted at the lower figure,
    # this lands on a different side of the cap.
    if denial is None:
        attempt(tmp_path, *rows, tag="gen-b", price=next_price)
    else:
        with pytest.raises(SpendDenied, match=denial):
            attempt(tmp_path, *rows, tag="gen-b", price=next_price)


def test_a_ledger_row_without_a_call_tag_counts_at_its_cost(tmp_path: Path) -> None:
    other = Spec(TODAY, "scrape run for the parts site", "49.80")  # after gen-1's row
    with pytest.raises(SpendDenied, match=r"would reach 50\.20 against the 50\.00 cap"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), other)


def test_every_ledger_row_of_a_tag_counts_not_just_the_largest(tmp_path: Path) -> None:
    # `dup-1` has two rows, 25.00 each, and one journal entry for 25.00. Max over its rows, or
    # the journal figure alone, would hide 25.00 of spend.
    dup = (call("dup-1", "25.00"), call("dup-1", "25.00"))
    journal = tmp_path / "j.jsonl"
    record_outcome(journal, "dup-1", status="authorized", price="25.00")
    with pytest.raises(SpendDenied, match=r"would reach 50\.40 against the 50\.00 cap"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"), *dup)


def test_every_journal_authorization_of_a_tag_counts(tmp_path: Path) -> None:
    # A hand-edited journal with two authorizations for one tag: both prices were committed.
    entry = '{"tag":"dup-1","status":"authorized","price":"25.00"}\n'
    (tmp_path / "j.jsonl").write_text(entry * 2)
    with pytest.raises(SpendDenied, match=r"would reach 50\.40 against the 50\.00 cap"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


@pytest.mark.parametrize("estimate", ["20.00", "0.40"])
def test_a_recorded_outcome_cost_above_the_estimate_counts(tmp_path: Path, estimate: str) -> None:
    # The call was authorized at the estimate and cost 45.00; the ledger row was never corrected.
    attempt(tmp_path, cap_approval(), call("gen-a", estimate), tag="gen-a", price=estimate)
    record_outcome(tmp_path / "j.jsonl", "gen-a", status="succeeded", cost=Decimal("45.00"))
    rows = (cap_approval(), call("gen-a", estimate), call("gen-b", "10.00"))
    with pytest.raises(SpendDenied, match=r"would reach 55\.00 against the 50\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-b", price="10.00")


@pytest.mark.parametrize(
    ("outcome_cost", "next_price", "denial"),
    [
        # An outcome below the authorization, or with no cost, still counts at the 20.00.
        (Decimal("5.00"), "30.00", None),
        (Decimal("5.00"), "31.00", r"would reach 51\.00 against the 50\.00 cap"),
        (None, "30.00", None),
        (None, "31.00", r"would reach 51\.00 against the 50\.00 cap"),
    ],
    ids=["lower-ok", "lower-over", "no-cost-ok", "no-cost-over"],
)
def test_a_recorded_outcome_never_lowers_the_authorized_price(
    tmp_path: Path, outcome_cost: Decimal | None, next_price: str, denial: str | None
) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "20.00"), tag="gen-a", price="20.00")
    if outcome_cost is None:
        record_outcome(tmp_path / "j.jsonl", "gen-a", status="succeeded")
    else:
        record_outcome(tmp_path / "j.jsonl", "gen-a", status="succeeded", cost=outcome_cost)
    rows = (cap_approval(), call("gen-b", next_price))  # gen-a's row is gone from the ledger
    if denial is None:
        attempt(tmp_path, *rows, tag="gen-b", price=next_price)
    else:
        with pytest.raises(SpendDenied, match=denial):
            attempt(tmp_path, *rows, tag="gen-b", price=next_price)


def test_an_outcome_for_a_tag_with_no_authorization_or_row_still_counts(tmp_path: Path) -> None:
    # The journal alone knows gen-0 cost 45.00: no authorization entry survives, and no row.
    record_outcome(tmp_path / "j.jsonl", "gen-0", status="succeeded", cost=Decimal("45.00"))
    with pytest.raises(SpendDenied, match=r"would reach 55\.00 against the 50\.00 cap"):
        attempt(tmp_path, cap_approval(), call("gen-1", "10.00"), price="10.00")


def test_a_ledger_cost_above_the_recorded_outcome_still_counts(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "1.00"), tag="gen-a", price="1.00")
    record_outcome(tmp_path / "j.jsonl", "gen-a", status="succeeded", cost=Decimal("5.00"))
    # The ledger row was corrected to the real 40.00 and sits below gen-b's row, so only the
    # reconciled check sees it: 40.00 + 11.00 passes the cap.
    rows = (cap_approval(), call("gen-b", "11.00"), call("gen-a", "40.00"))
    with pytest.raises(SpendDenied, match=r"would reach 51\.00 against the 50\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-b", price="11.00")


def test_an_outcome_with_a_null_cost_counts_like_one_without_a_cost(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "20.00"), tag="gen-a", price="20.00")
    record_outcome(tmp_path / "j.jsonl", "gen-a", status="succeeded", cost=None)
    attempt(tmp_path, cap_approval(), call("gen-b", "30.00"), tag="gen-b", price="30.00")


def test_a_tag_counts_at_its_highest_recorded_outcome_not_the_sum(tmp_path: Path) -> None:
    attempt(tmp_path, cap_approval(), call("gen-a", "1.00"), tag="gen-a", price="1.00")
    # Two reports of the same call: the second corrects the first, so they are not added.
    record_outcome(tmp_path / "j.jsonl", "gen-a", status="succeeded", cost=Decimal("20.00"))
    record_outcome(tmp_path / "j.jsonl", "gen-a", status="reconciled", cost=Decimal("25.00"))
    rows = (cap_approval(), call("gen-b", "25.00"))
    attempt(tmp_path, *rows, tag="gen-b", price="25.00")  # 25.00 + 25.00 reaches the cap exactly
    with pytest.raises(SpendDenied, match=r"would reach 50\.01 against the 50\.00 cap"):
        attempt(tmp_path, cap_approval(), call("gen-c", "0.01"), tag="gen-c", price="0.01")


@pytest.mark.parametrize(
    "cost",
    ['"cost":45', '"cost":45.0', '"cost":"abc"', '"cost":"-1"', '"cost":"NaN"', '"cost":true'],
)
def test_a_journal_entry_with_a_malformed_cost_denies_everything(tmp_path: Path, cost: str) -> None:
    (tmp_path / "j.jsonl").write_text('{"tag":"gen-0","status":"succeeded",' + cost + "}\n")
    with pytest.raises(SpendDenied, match=r"j\.jsonl line 1.*cost"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


@pytest.mark.parametrize("cost", [45.0, 45, "45.00", True])
def test_record_outcome_refuses_a_cost_that_is_not_a_decimal(tmp_path: Path, cost: object) -> None:
    with pytest.raises(TypeError, match="cost"):
        record_outcome(tmp_path / "j.jsonl", "gen-1", status="succeeded", cost=cost)
    assert not (tmp_path / "j.jsonl").exists()


@pytest.mark.parametrize("cost", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")])
def test_record_outcome_refuses_a_negative_or_non_finite_cost(
    tmp_path: Path, cost: Decimal
) -> None:
    with pytest.raises(ValueError, match="cost"):
        record_outcome(tmp_path / "j.jsonl", "gen-1", status="succeeded", cost=cost)
    assert not (tmp_path / "j.jsonl").exists()


@pytest.mark.parametrize("cost", [Decimal("-0"), Decimal("-0.00")])
def test_record_outcome_refuses_a_signed_zero_cost(tmp_path: Path, cost: Decimal) -> None:
    # `Decimal("-0") < 0` is False, so a sign check on the value lets it through; it would be
    # journaled as "-0", which the journal reader rejects, and every later call would be denied.
    with pytest.raises(ValueError, match="cost"):
        record_outcome(tmp_path / "j.jsonl", "gen-1", status="succeeded", cost=cost)
    assert not (tmp_path / "j.jsonl").exists()


def test_record_outcome_still_accepts_an_unsigned_zero_cost(tmp_path: Path) -> None:
    journal = tmp_path / "j.jsonl"
    record_outcome(journal, "gen-1", status="failed", cost=Decimal("0.00"))
    (entry,) = journal_entries(journal)
    assert entry["cost"] == "0.00"
    attempt(tmp_path, cap_approval(), call("gen-2", "0.40"), tag="gen-2")  # the journal reads back


@pytest.mark.parametrize(
    "price",
    ["", ',"price":0.4', ',"price":"abc"', ',"price":"-1"', ',"price":"NaN"', ',"price":null'],
)
def test_an_authorized_journal_entry_without_a_valid_price_denies_everything(
    tmp_path: Path, price: str
) -> None:
    (tmp_path / "j.jsonl").write_text('{"tag":"gen-0","status":"authorized"' + price + "}\n")
    with pytest.raises(SpendDenied, match=r"j\.jsonl line 1.*price"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


AUTHORIZED_GEN_0 = '{"tag":"gen-0","status":"authorized","price":"0.40"}'


@pytest.mark.parametrize("writer", ["authorize", "record_outcome"])
def test_an_unterminated_last_journal_line_is_denied_or_repaired_not_glued_to_the_next_entry(
    tmp_path: Path, writer: str
) -> None:
    # A crash or a short write left the last entry without its newline. Appending straight after
    # it would glue two entries onto one line and corrupt both. The guard repairs: it ends the
    # line first, so the old entry is still read and the new one is a line of its own.
    journal = tmp_path / "j.jsonl"
    journal.write_text(AUTHORIZED_GEN_0)  # no trailing newline
    if writer == "authorize":
        attempt(tmp_path, cap_approval(), call("gen-0", "0.40"), call("gen-1", "0.40"), tag="gen-1")
    else:
        record_outcome(journal, "gen-1", status="succeeded", cost=Decimal("0.40"))

    assert journal.read_text().endswith("\n")
    first, second = journal_entries(journal)  # each line parses on its own
    assert first == {"tag": "gen-0", "status": "authorized", "price": "0.40"}
    assert second["tag"] == "gen-1"
    # The repaired journal still reads back, and gen-0 stays spent.
    with pytest.raises(SpendDenied, match="already"):
        attempt(tmp_path, cap_approval(), call("gen-0", "0.40"), call("gen-1", "0.40"), tag="gen-0")


def test_an_unterminated_last_line_is_counted_before_the_guard_repairs_it(tmp_path: Path) -> None:
    # The repair must not hide the entry it terminates: gen-0's 40.00 still counts against the cap.
    journal = tmp_path / "j.jsonl"
    journal.write_text(AUTHORIZED_GEN_0.replace('"0.40"', '"40.00"'))
    rows = (cap_approval(), call("gen-1", "10.50"))
    with pytest.raises(SpendDenied, match=r"would reach 50\.50 against the 50\.00 cap"):
        attempt(tmp_path, *rows, tag="gen-1", price="10.50")


def test_a_torn_unterminated_line_is_ended_before_an_outcome_lands_and_still_denies(
    tmp_path: Path,
) -> None:
    # A line cut off mid-entry is not valid JSON: it is ended, so the outcome that follows is a
    # line of its own, and `authorize` keeps denying until a human removes the torn line.
    journal = tmp_path / "j.jsonl"
    journal.write_text('{"tag":"gen-0","status":"auth')
    record_outcome(journal, "gen-1", status="succeeded", cost=Decimal("0.40"))

    lines = journal.read_text().splitlines()
    assert lines[0] == '{"tag":"gen-0","status":"auth'
    assert json.loads(lines[1])["tag"] == "gen-1"
    with pytest.raises(SpendDenied, match=r"j\.jsonl line 1 is not valid JSON"):
        attempt(tmp_path, cap_approval(), call("gen-2", "0.40"), tag="gen-2")


def test_a_terminated_journal_gets_no_extra_blank_line(tmp_path: Path) -> None:
    journal = tmp_path / "j.jsonl"
    journal.write_text(AUTHORIZED_GEN_0 + "\n")
    record_outcome(journal, "gen-0", status="succeeded", cost=Decimal("0.40"))
    assert "\n\n" not in journal.read_text()
    assert len(journal.read_text().splitlines()) == 2


def test_ledger_is_read_at_call_time(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.md"
    journal = tmp_path / "j.jsonl"
    ledger.write_text(render(cap_approval(), call("gen-1", "0.40")), "utf-8")
    grant("gen-1", ledger, journal)
    with pytest.raises(SpendDenied, match="no ledger row"):
        grant("gen-2", ledger, journal)

    # The row appears after the first call: the next call must see it.
    ledger.write_text(render(cap_approval(), call("gen-1", "0.40"), call("gen-2", "0.40")), "utf-8")
    assert grant("gen-2", ledger, journal).cost == Decimal("0.40")


def test_authorize_defaults_to_the_default_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state" / "spend-journal.jsonl"
    monkeypatch.setattr(spend_mod, "default_journal", lambda: target)
    authorize(
        "gen-1",
        Decimal("0.40"),
        ledger=write_ledger(tmp_path, cap_approval(), call("gen-1", "0.40")),
        today=TODAY,
        session=SESSION,
    )
    assert [entry["tag"] for entry in journal_entries(target)] == ["gen-1"]


def test_default_journal_does_not_depend_on_m3_work_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "one"))
    first = default_journal()
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "two"))
    assert default_journal() == first
    assert first == ACCOUNT_HOME / ".local" / "state" / "m3-tool" / "spend-journal.jsonl"
    assert not first.is_relative_to(tmp_path)


def test_default_journal_does_not_depend_on_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `Path.home()` follows $HOME, so a journal under it would move with the environment.
    monkeypatch.setenv("HOME", str(tmp_path / "one"))
    first = default_journal()
    monkeypatch.setenv("HOME", str(tmp_path / "two"))
    monkeypatch.delenv("HOME")
    assert default_journal() == first
    assert first == ACCOUNT_HOME / ".local" / "state" / "m3-tool" / "spend-journal.jsonl"
    assert not first.is_relative_to(tmp_path)


def fake_account(home: str) -> Callable[[int], pwd.struct_passwd]:
    """An account database entry with `home`: moves the account without moving $HOME."""

    def lookup(uid: int) -> pwd.struct_passwd:
        return pwd.struct_passwd(("tester", "x", uid, uid, "", home, "/bin/sh"))

    return lookup


def test_a_tag_authorized_under_one_home_is_denied_under_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = tmp_path / "account"
    monkeypatch.setattr(pwd, "getpwuid", fake_account(str(account)))
    ledger = write_ledger(tmp_path, cap_approval(), call("gen-1", "0.40"))

    # No `journal` argument: the default journal is what must not move with $HOME.
    monkeypatch.setenv("HOME", str(tmp_path / "home-a"))
    authorize("gen-1", Decimal("0.40"), ledger=ledger, today=TODAY, session=SESSION)
    monkeypatch.setenv("HOME", str(tmp_path / "home-b"))
    with pytest.raises(SpendDenied, match="already"):
        authorize("gen-1", Decimal("0.40"), ledger=ledger, today=TODAY, session=SESSION)

    journal = account / ".local" / "state" / "m3-tool" / "spend-journal.jsonl"
    assert [entry["tag"] for entry in journal_entries(journal)] == ["gen-1"]
    assert not (tmp_path / "home-a").exists()
    assert not (tmp_path / "home-b").exists()


@pytest.mark.parametrize("home", ["", "relative/home"])
def test_default_journal_is_denied_without_an_absolute_account_home(
    monkeypatch: pytest.MonkeyPatch, home: str
) -> None:
    monkeypatch.setattr(pwd, "getpwuid", fake_account(home))
    with pytest.raises(SpendDenied, match="account database"):
        default_journal()


def test_default_journal_is_denied_when_the_account_has_no_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(uid: int) -> pwd.struct_passwd:
        raise KeyError(f"getpwuid(): uid not found: {uid}")

    monkeypatch.setattr(pwd, "getpwuid", missing)
    with pytest.raises(SpendDenied, match="account database"):
        default_journal()


def test_authorize_waits_while_another_holder_has_the_exclusive_lock(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, cap_approval(), call("gen-1", "0.40"))
    journal = tmp_path / "j.jsonl"
    authorized: list[LedgerRow] = []

    def run() -> None:
        authorized.append(grant("gen-1", ledger, journal))

    # The lock file is `<journal>.lock`: take it the way another process would.
    holder = os.open(tmp_path / "j.jsonl.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    worker = threading.Thread(target=run, daemon=True)
    try:
        worker.start()
        worker.join(0.5)
        assert worker.is_alive(), "authorize ran without waiting for the lock"
        assert not journal.exists()
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    worker.join(10)
    assert not worker.is_alive()
    assert [row.cost for row in authorized] == [Decimal("0.40")]


# Worker processes. They are module-level so a spawned child can import them by name.


def _authorize_after_barrier(
    barrier: multiprocessing.synchronize.Barrier,
    ledger: Path,
    journal: Path,
    results: multiprocessing.queues.Queue[tuple[str, str]],
) -> None:
    barrier.wait()
    try:
        row = grant("gen-last", ledger, journal)
    except SpendDenied as denied:
        results.put(("denied", str(denied)))
    else:
        results.put(("authorized", str(row.cost)))


def _authorize_then_crash(ledger: Path, journal: Path) -> None:
    grant("gen-1", ledger, journal)
    os._exit(7)  # no cleanup, no outcome: the process dies before it makes the paid call


def test_two_concurrent_authorizations_for_the_last_affordable_row_let_exactly_one_succeed(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path, cap_approval(), call("prior-1", "49.60"), call("gen-last", "0.40")
    )
    journal = tmp_path / "j.jsonl"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results: multiprocessing.queues.Queue[tuple[str, str]] = context.Queue()
    workers = [
        context.Process(target=_authorize_after_barrier, args=(barrier, ledger, journal, results))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    outcomes = sorted(results.get(timeout=60) for _ in workers)
    for worker in workers:
        worker.join(30)
        assert worker.exitcode == 0

    assert [status for status, _ in outcomes] == ["authorized", "denied"]
    assert "already" in outcomes[1][1]
    entries = journal_entries(journal)
    assert [(entry["tag"], entry["status"]) for entry in entries] == [("gen-last", "authorized")]


def test_authorization_survives_a_crash_before_the_call(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, cap_approval(), call("gen-1", "0.40"))
    journal = tmp_path / "j.jsonl"
    crashed = multiprocessing.get_context("spawn").Process(
        target=_authorize_then_crash, args=(ledger, journal)
    )
    crashed.start()
    crashed.join(60)
    assert crashed.exitcode == 7

    (entry,) = journal_entries(journal)
    assert (entry["tag"], entry["status"]) == ("gen-1", "authorized")
    # A second process finds the tag spent and is denied.
    with pytest.raises(SpendDenied, match="already"):
        grant("gen-1", ledger, journal)


def test_a_short_write_is_completed_never_journaled_torn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write
    sizes: list[int] = []

    def three_bytes_at_a_time(fd: int, data: bytes) -> int:
        sizes.append(len(data))
        return real_write(fd, data[:3])

    monkeypatch.setattr(spend_mod, "_write", three_bytes_at_a_time)
    attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))

    assert len(sizes) > 1, "the writer was not asked to finish the entry"
    (entry,) = journal_entries(tmp_path / "j.jsonl")
    assert (entry["tag"], entry["status"]) == ("gen-1", "authorized")


def test_an_incomplete_write_does_not_authorize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write
    calls: list[int] = []

    def disk_fills_up(fd: int, data: bytes) -> int:
        calls.append(len(data))
        assert len(calls) < 100, "the guard kept retrying a writer that makes no progress"
        return real_write(fd, data[:5]) if len(calls) == 1 else 0

    monkeypatch.setattr(spend_mod, "_write", disk_fills_up)
    with pytest.raises(SpendDenied, match="incomplete write"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))

    # What is left is a torn line, which denies everything until a human removes it. That is safe:
    # no authorization was returned for it, so no call was made.
    monkeypatch.setattr(spend_mod, "_write", real_write)
    with pytest.raises(SpendDenied, match=r"j\.jsonl line 1"):
        attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))


def test_record_outcome_raises_on_an_incomplete_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def no_progress(fd: int, data: bytes) -> int:
        calls.append(len(data))
        assert len(calls) < 100, "the guard kept retrying a writer that makes no progress"
        return 0

    monkeypatch.setattr(spend_mod, "_write", no_progress)
    with pytest.raises(OSError, match="incomplete write"):
        record_outcome(tmp_path / "j.jsonl", "gen-1", status="failed")


# --- record_outcome ---


def test_record_outcome_appends_without_rewriting(tmp_path: Path) -> None:
    journal = tmp_path / "j.jsonl"
    attempt(tmp_path, cap_approval(), call("gen-1", "0.40"))
    before = journal.read_bytes()

    record_outcome(journal, "gen-1", status="succeeded", cost=Decimal("0.38"), request_id="r-1")

    assert journal.read_bytes().startswith(before)
    authorized, outcome = journal_entries(journal)
    assert authorized["status"] == "authorized"
    assert outcome["tag"] == "gen-1"
    assert outcome["status"] == "succeeded"
    assert outcome["cost"] == "0.38"  # Decimal is written as a string, never as a float
    assert outcome["request_id"] == "r-1"
    assert isinstance(outcome["at"], str)


def test_record_outcome_creates_the_journal_when_it_is_missing(tmp_path: Path) -> None:
    journal = tmp_path / "state" / "j.jsonl"
    record_outcome(journal, "gen-1", status="failed")
    assert [entry["tag"] for entry in journal_entries(journal)] == ["gen-1"]


def test_record_outcome_keeps_the_tag_and_time_it_computes(tmp_path: Path) -> None:
    journal = tmp_path / "j.jsonl"
    record_outcome(journal, "gen-1", at="yesterday")
    (entry,) = journal_entries(journal)
    assert entry["at"] != "yesterday"


# --- parse_ledger, call_tag, session_label ---


def test_parse_ledger_skips_header_and_separator_and_numbers_the_lines() -> None:
    rows = parse_ledger(render(cap_approval(), call("gen-1", "0.40")))
    assert [row.line for row in rows] == [FIRST_ROW_LINE, FIRST_ROW_LINE + 1]
    cap, generation = rows
    assert cap.purpose == f"cap approved by the user session:{SESSION}"
    assert generation == LedgerRow(
        line=FIRST_ROW_LINE + 1,
        date=TODAY,
        session_cap=Decimal("50"),
        service="fal",
        purpose="spike:gen-1 test generation",
        units="1",
        cost=Decimal("0.40"),
        running=Decimal("0.40"),
    )


def test_parse_ledger_reads_dash_cells_as_none() -> None:
    text = PREAMBLE + HEADER + "| 2026-11-24 | — | — | note | — | 0.00 | — |\n"
    (row,) = parse_ledger(text)
    assert row.session_cap is None
    assert row.running is None


def test_parse_ledger_reads_the_real_ledger() -> None:
    text = REAL_LEDGER.read_text("utf-8")
    rows = parse_ledger(text)
    assert rows, "docs/spend-ledger.md has no data rows"
    assert all(isinstance(row.cost, Decimal) for row in rows)
    # The guard reads prose, then one table that runs to the end of the file.
    assert text.rstrip().splitlines()[-1].startswith("|"), "the table must be last in the ledger"


def test_the_real_ledger_tells_the_editor_the_table_stays_last() -> None:
    intro = REAL_LEDGER.read_text("utf-8").split("| Date |")[0]
    assert "must stay last" in intro
    assert "nothing may follow" in intro


def test_parse_ledger_of_an_empty_table_has_no_rows() -> None:
    assert parse_ledger(PREAMBLE + HEADER) == []
    assert parse_ledger("") == []


_PRE = "| 2026-11-24 | $50 | fal | spike:a x | 1 |"


@pytest.mark.parametrize(
    ("row", "why"),
    [
        ("| 2026-11-24 | $50 | fal | spike:a x | 1 | 0.40 |", "7 cells"),
        ("| 2026-11-24 | $50 | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 | extra |", "7 cells"),
        ("| 24-11-2026 | $50 | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 |", "date"),
        ("| 2026-02-30 | $50 | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 |", "date"),
        ("| 20261124 | $50 | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 |", "date"),
        ("| 2026-11-24 | fifty | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 |", "session cap"),
        ("| 2026-11-24 | $-5 | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 |", "session cap"),
        (f"{_PRE} 0,40 | 0.40 / 50.00 |", "cost"),
        (f"{_PRE} -0.40 | 0.40 / 50.00 |", "cost"),
        (f"{_PRE} 1e3 | 0.40 / 50.00 |", "cost"),
        (f"{_PRE} NaN | 0.40 / 50.00 |", "cost"),
        (f"{_PRE} $0.40 | 0.40 / 50.00 |", "cost"),
        (f"{_PRE} 0.40 | 0.40 of 50.00 |", "running"),
        (f"{_PRE} 0.40 | 0.40 |", "running"),
        (f"{_PRE} 0.40 | 0.40 / fifty |", "running"),
    ],
)
def test_parse_ledger_malformed_row_raises_naming_the_line(row: str, why: str) -> None:
    text = PREAMBLE + HEADER + row + "\n"
    with pytest.raises(SpendDenied, match=rf"line {FIRST_ROW_LINE}: .*{why}"):
        parse_ledger(text)


def test_parse_ledger_names_the_line_of_a_later_bad_row() -> None:
    text = render(cap_approval()) + "| bad |\n"
    with pytest.raises(SpendDenied, match=rf"line {FIRST_ROW_LINE + 1}:"):
        parse_ledger(text)


def test_parse_ledger_rejects_a_table_with_another_header() -> None:
    swapped = HEADER.replace("Service | Purpose", "Purpose | Service")
    with pytest.raises(SpendDenied, match="line 5: .*header"):
        parse_ledger(PREAMBLE + swapped + "|---|---|---|---|---|---|---|\n")


def test_parse_ledger_rejects_a_row_before_the_header() -> None:
    row = "| 2026-11-24 | $50 | fal | spike:a x | 1 | 0.40 | 0.40 / 50.00 |\n"
    with pytest.raises(SpendDenied, match="line 5: .*header"):
        parse_ledger(PREAMBLE + row + HEADER)


LOST_PIPE_ROW = "2026-11-24 | $50 | fal | spike:big x | 1 | 60.00 | 60.40 / 50.00 |"
NOT_A_ROW = r"is not a table row"


def test_a_row_that_lost_its_leading_pipe_is_not_skipped_as_prose(tmp_path: Path) -> None:
    # A valid 0.40 call, then a 60.00 row that lost its leading '|': it must not vanish from the
    # total and leave gen-1 authorized against a 50.00 cap.
    ledger = tmp_path / "ledger.md"
    ledger.write_text(render(cap_approval(), call("gen-1", "0.40")) + LOST_PIPE_ROW + "\n")
    with pytest.raises(SpendDenied, match=rf"line 9: .*{NOT_A_ROW}"):
        authorize(
            "gen-1",
            Decimal("0.40"),
            ledger=ledger,
            journal=tmp_path / "j.jsonl",
            today=TODAY,
            session=SESSION,
        )
    assert not (tmp_path / "j.jsonl").exists()


@pytest.mark.parametrize("gap", ["", "\n", "\nA note.\n\n"])
def test_parse_ledger_denies_a_table_line_without_its_leading_pipe(gap: str) -> None:
    text = render(cap_approval(), call("gen-1", "0.40")) + gap + LOST_PIPE_ROW + "\n"
    with pytest.raises(SpendDenied, match=NOT_A_ROW):
        parse_ledger(text)


def test_parse_ledger_denies_a_lost_pipe_row_between_the_header_and_the_separator() -> None:
    lines = (PREAMBLE + HEADER).splitlines()
    text = "\n".join([*lines[:-1], LOST_PIPE_ROW, lines[-1]]) + "\n"
    with pytest.raises(SpendDenied, match=r"line 6: .*separator"):
        parse_ledger(text)


# A 60.00 row pasted in without its ASCII table frame. Each must be denied once the table has
# started, or its cost escapes the cap.
FIELDS = ["2026-11-24", "$50", "fal", "spike:big x", "1", "60.00", "60.40 / 50.00"]


def barred(bar: str) -> str:
    return f"{bar} " + f" {bar} ".join(FIELDS) + f" {bar}"


BARS = {
    "fullwidth bars": "\uff5c",
    "box drawing bars": "\u2502",
    "heavy box bars": "\u2503",
    "double box bars": "\u2551",
    "broken bars": "\u00a6",
    "divides bars": "\u2223",
    "light vertical bars": "\u2758",
    "vertical line extension bars": "\u23d0",
}
# Bars the old denylist did not list: any bar is denied now, because the rule is an allowlist.
UNLISTED_BARS = {
    "U+2506": "\u2506",
    "U+2507": "\u2507",
    "U+254E": "\u254e",
    "U+FE31": "\ufe31",
    "U+01C0": "\u01c0",
    "U+2016": "\u2016",
    "U+FFE8": "\uffe8",
    "U+23AA": "\u23aa",
    "U+2759": "\u2759",
    "U+275A": "\u275a",
    "U+4E28": "\u4e28",
    "U+3163": "\u3163",
}
SPACED = "  ".join(FIELDS)
UNFRAMED_ROWS = {
    **{name: barred(bar) for name, bar in BARS.items()},
    **{f"unlisted bar {name}": barred(bar) for name, bar in UNLISTED_BARS.items()},
    "tab separated": "\t".join(FIELDS),
    "tab separated, no date": "\t".join(["—", *FIELDS[2:]]),
    "space separated": SPACED,
    "space separated, date cell lost": "  ".join(FIELDS[1:]),
    "bullet prefix": f"* {SPACED}",
    "dash prefix": f"- {SPACED}",
    "quote prefix": f"> {SPACED}",
    "zero-width space before the date": f"\u200b{SPACED}",
    "bullet before a framed row": f"* | {' | '.join(FIELDS)} |",
    "quote before a framed row": f"> | {' | '.join(FIELDS)} |",
    "zero-width space before a framed row": f"\u200b| {' | '.join(FIELDS)} |",
}


@pytest.mark.parametrize("row", UNFRAMED_ROWS.values(), ids=UNFRAMED_ROWS.keys())
def test_parse_ledger_denies_a_row_in_another_shape_after_the_table_started(row: str) -> None:
    with pytest.raises(SpendDenied, match=rf"line 9: .*{NOT_A_ROW}"):
        parse_ledger(render(cap_approval(), call("gen-1", "0.40")) + row + "\n")


@pytest.mark.parametrize("row", UNFRAMED_ROWS.values(), ids=UNFRAMED_ROWS.keys())
def test_a_row_in_another_shape_does_not_slip_past_the_cap(tmp_path: Path, row: str) -> None:
    ledger = tmp_path / "ledger.md"
    ledger.write_text(render(cap_approval(), call("gen-1", "0.40")) + row + "\n")
    with pytest.raises(SpendDenied, match=rf"line 9: .*{NOT_A_ROW}"):
        authorize(
            "gen-1",
            Decimal("0.40"),
            ledger=ledger,
            journal=tmp_path / "j.jsonl",
            today=TODAY,
            session=SESSION,
        )
    assert not (tmp_path / "j.jsonl").exists()


@pytest.mark.parametrize(
    "prose",
    [
        "All amounts are in USD.",
        "Updated 2026-11-24",
        "<!-- 2026-11-24 -->",
        "Total = 12 / 50",
        "A tab\there, but no amount.",
        "    an indented note",
        "## Notes",
    ],
)
def test_parse_ledger_denies_prose_after_the_table(prose: str) -> None:
    # The ledger is prose, then one table that runs to the end of the file, so any non-blank
    # line after the header must be a table row.
    with pytest.raises(SpendDenied, match=rf"line 9: .*{NOT_A_ROW}"):
        parse_ledger(render(cap_approval(), call("gen-1", "0.40")) + prose + "\n")


def test_parse_ledger_denies_prose_after_a_blank_line_after_the_table() -> None:
    text = render(cap_approval()) + "\n\nNotes follow.\n"
    with pytest.raises(SpendDenied, match=rf"line 10: .*{NOT_A_ROW}"):
        parse_ledger(text)


def test_parse_ledger_allows_blank_lines_after_and_between_rows() -> None:
    text = render(cap_approval()) + "\n\n" + render(call("gen-1", "0.40")).split("\n")[-2] + "\n\n"
    assert len(parse_ledger(text)) == 2


def test_parse_ledger_denies_prose_between_the_header_and_the_separator() -> None:
    lines = (PREAMBLE + HEADER).splitlines()
    text = "\n".join([*lines[:-1], "A note.", lines[-1]]) + "\n"
    with pytest.raises(SpendDenied, match=r"line 6: .*separator"):
        parse_ledger(text)


def test_parse_ledger_rejects_a_header_without_its_separator() -> None:
    text = PREAMBLE + HEADER.splitlines()[0] + "\n" + "| 2026-11-24 | $50 | fal | x | 1 | 0 | — |\n"
    with pytest.raises(SpendDenied, match="line 6: .*separator"):
        parse_ledger(text)


@pytest.mark.parametrize(
    ("purpose", "tag"),
    [
        ("spike:gen-rodin25-01 Rodin 2.5 hero shot", "gen-rodin25-01"),
        ("spike:gen-1", "gen-1"),
        ("cap approved by the user session:2026-11-24-a", None),
        ("cap approved by the user", None),
        ("spike: gen-1 spaced", None),
        ("spike:Gen-1 upper", None),
        ("spike:gen_1 underscore", None),
        ("note spike:gen-1 not first", None),
        ("", None),
    ],
)
def test_call_tag(purpose: str, tag: str | None) -> None:
    assert call_tag(purpose) == tag


@pytest.mark.parametrize(
    ("purpose", "label"),
    [
        ("cap approved by the user session:2026-11-24-a", "2026-11-24-a"),
        ("cap approved by the user session:abc with trailing words", "abc"),
        ("cap approved by the user", None),
        ("cap approved by the user session:", None),
        ("cap approved by the user session:UPPER", None),
        ("cap approved by the user session:under_score", None),
        ("spike:gen-1 session:2026-11-24-a", None),
        ("approved session:2026-11-24-a", None),
        ("", None),
    ],
)
def test_session_label(purpose: str, label: str | None) -> None:
    assert session_label(purpose) == label
