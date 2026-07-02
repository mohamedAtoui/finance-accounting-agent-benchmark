"""Gate 1: the ledger engine must be correct before anything builds on it."""

from __future__ import annotations

import pytest

from finbalance import coa as C
from finbalance.ledger import (
    Ledger,
    UnbalancedEntryError,
    UnknownAccountError,
    replay,
)
from finbalance.model import JournalEntry, JournalLine
from finbalance.money import fmt, parse_amount, within_tolerance


def je(entry_id, *lines, source="ADJ"):
    return JournalEntry(entry_id=entry_id, date="2025-01-31", memo="t", lines=tuple(lines), source=source)


# ---------------------------------------------------------------- money


def test_parse_amount_rounds_half_up():
    assert parse_amount("123.45") == 12345
    assert parse_amount("-0.10") == -10
    assert parse_amount("0.005") == 1  # half up
    assert parse_amount(100) == 10000
    assert parse_amount("1.005") == 101  # half up at the cent


def test_fmt_and_tolerance():
    assert fmt(-12345) == "-123.45"
    assert fmt(5) == "0.05"
    assert within_tolerance(1000, 1001) is True   # 1 cent
    assert within_tolerance(1000, 1002) is False


# ---------------------------------------------------------------- posting


def test_post_rejects_unbalanced():
    led = Ledger(C.build_chart_of_accounts(), {})
    bad = je("e1", JournalLine(C.BANK_FEES, debit=100), JournalLine(C.CASH, credit=99))
    with pytest.raises(UnbalancedEntryError):
        led.post(bad)


def test_post_rejects_unknown_account():
    led = Ledger(C.build_chart_of_accounts(), {})
    bad = je("e1", JournalLine("9999", debit=100), JournalLine(C.CASH, credit=100))
    with pytest.raises(UnknownAccountError):
        led.post(bad)


def test_debit_credit_signs():
    coa = C.build_chart_of_accounts()
    led = Ledger(coa, {})
    # Dr Bank Fees 100 / Cr Cash 100
    led.post(je("e1", JournalLine(C.BANK_FEES, debit=100), JournalLine(C.CASH, credit=100)))
    # Expense (debit-normal) goes up; Cash (debit-normal) goes down.
    assert led.balance(C.BANK_FEES) == 100
    assert led.balance(C.CASH) == -100
    # A credit to a liability increases it.
    led.post(je("e2", JournalLine(C.OP_EXPENSE, debit=250), JournalLine(C.ACCRUED_LIAB, credit=250)))
    assert led.balance(C.ACCRUED_LIAB) == 250


def test_trial_balance_check_zero_when_balanced():
    coa = C.build_chart_of_accounts()
    # Opening: Cash 1000 (Dr), Common Stock 1000 (Cr). In natural units both +1000.
    opening = {C.CASH: 1000, C.COMMON_STOCK: 1000}
    led = Ledger(coa, opening)
    assert led.trial_balance_check() == 0
    # Post a balanced entry; still balanced.
    led.post(je("e1", JournalLine(C.OP_EXPENSE, debit=300), JournalLine(C.CASH, credit=300)))
    assert led.trial_balance_check() == 0


# ---------------------------------------------------------------- replay


def test_replay_collects_rejects_without_raising():
    coa = C.build_chart_of_accounts()
    good = je("ok", JournalLine(C.BANK_FEES, debit=100), JournalLine(C.CASH, credit=100))
    bad = je("bad", JournalLine(C.BANK_FEES, debit=100), JournalLine(C.CASH, credit=99))
    res = replay(coa, {C.CASH: 500, C.COMMON_STOCK: 500}, [good, bad])
    assert res.final[C.BANK_FEES] == 100
    assert res.final[C.CASH] == 400
    assert [r[0] for r in res.rejected] == ["bad"]
    assert C.BANK_FEES in res.touched and C.CASH in res.touched


def test_replay_starts_from_opening():
    coa = C.build_chart_of_accounts()
    res = replay(coa, {C.CASH: 1000, C.COMMON_STOCK: 1000}, [])
    assert res.final[C.CASH] == 1000  # untouched opening preserved
