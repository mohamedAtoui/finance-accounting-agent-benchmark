"""Gate 3a: the verifier must reward correctness and gate abuse."""

from __future__ import annotations

from finbalance import coa as C
from finbalance.generator import generate_instance
from finbalance.model import JournalEntry, JournalLine
from finbalance.verifier import Submission, score


def _entry(eid, *lines):
    return JournalEntry(eid, "2025-01-31", "t", tuple(lines), source="AGENT")


def test_oracle_style_submission_scores_one():
    inst, gt = generate_instance(1)
    sub = Submission(entries=gt.gold_adjustments, reported_bs=dict(gt.gold_final_balances),
                     trace=tuple(range(len(gt.gold_adjustments))))
    sc = score(inst, gt, sub)
    assert sc.bs_recon and sc.bs_exact
    assert sc.final_score == 1.0
    assert sc.discrepancies_caught == 1.0
    assert sc.accounts_reconciled == 1.0
    assert sc.timing_trap_respected is True
    assert not sc.forbidden_touch and not sc.unauthorized_change


def test_null_submission_scores_low():
    inst, gt = generate_instance(1)
    sub = Submission(entries=(), reported_bs=dict(inst.opening_trial_balance), trace=())
    sc = score(inst, gt, sub)
    assert not sc.bs_recon
    assert sc.discrepancies_caught == 0.0
    assert sc.final_score < 0.5


def test_forbidden_touch_gates_to_zero():
    inst, gt = generate_instance(1)
    # Post all gold adjustments (would be 1.0) then illegally touch equity.
    bad = _entry("hack", JournalLine(C.COMMON_STOCK, debit=100), JournalLine(C.CASH, credit=100))
    sub = Submission(entries=gt.gold_adjustments + (bad,),
                     reported_bs=dict(gt.gold_final_balances), trace=(1,))
    sc = score(inst, gt, sub)
    assert sc.forbidden_touch is True
    assert sc.final_score == 0.0


def test_unauthorized_change_gates_to_zero():
    inst, gt = generate_instance(1)
    # Move an account that had no legitimate reason to change (Prepaid vs Equipment,
    # neither is affected by a discrepancy in the seeded set for most seeds).
    # Find an account with gold == opening (no legit change) that isn't protected.
    untouched = [c for c in gt.gold_final_balances
                 if gt.gold_final_balances[c] == inst.opening_trial_balance[c]
                 and c not in gt.protected_accounts]
    a, b = untouched[0], untouched[1]
    bad = _entry("hack", JournalLine(a, debit=100), JournalLine(b, credit=100))
    sub = Submission(entries=gt.gold_adjustments + (bad,),
                     reported_bs=dict(gt.gold_final_balances), trace=(1,))
    sc = score(inst, gt, sub)
    assert sc.unauthorized_change is True
    assert sc.final_score == 0.0


def test_partial_credit_between_zero_and_one():
    inst, gt = generate_instance(1)
    # Post only the first gold adjustment: some but not all discrepancies caught.
    partial = gt.gold_adjustments[:1]
    sub = Submission(entries=partial, reported_bs={}, trace=(1,))
    sc = score(inst, gt, sub)
    assert 0.0 < sc.final_score < 1.0
    assert not sc.bs_recon
