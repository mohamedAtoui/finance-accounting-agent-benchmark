"""Gate 2: the generator's ground truth must be correct and reproducible."""

from __future__ import annotations

from finbalance.generator import generate_instance
from finbalance.ledger import Ledger, replay
from finbalance.model import DiscrepancyKind


def test_determinism_same_seed_same_instance():
    a, ga = generate_instance(7)
    b, gb = generate_instance(7)
    assert a == b
    assert ga == gb


def test_different_seeds_differ():
    a, _ = generate_instance(1)
    b, _ = generate_instance(2)
    assert a.opening_trial_balance != b.opening_trial_balance


def test_ground_truth_self_consistency_across_seeds():
    for seed in range(200):
        inst, gt = generate_instance(seed, k=4)
        # Opening and final both balance.
        assert Ledger(inst.chart_of_accounts, inst.opening_trial_balance).trial_balance_check() == 0
        assert Ledger(inst.chart_of_accounts, gt.gold_final_balances).trial_balance_check() == 0
        # Replaying gold adjustments from the opening reproduces gold exactly.
        res = replay(inst.chart_of_accounts, inst.opening_trial_balance, gt.gold_adjustments)
        assert res.rejected == ()
        assert res.final == gt.gold_final_balances


def test_timing_trap_always_present():
    _, gt = generate_instance(3)
    kinds = [d.kind for d in gt.discrepancies]
    assert DiscrepancyKind.TIMING_DIFFERENCE_NOADJUST in kinds
    trap = next(d for d in gt.discrepancies if d.kind == DiscrepancyKind.TIMING_DIFFERENCE_NOADJUST)
    assert trap.requires_adjustment is False
    assert trap.gold_entry is None
