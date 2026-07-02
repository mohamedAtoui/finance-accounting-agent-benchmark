"""Multi-month campaigns: oracle holds, a flawed agent compounds and cannot recover."""

from __future__ import annotations

from finbalance.agents import BaselineAgent, OracleAgent
from finbalance.campaign import run_campaign


def test_oracle_holds_across_months():
    for seed in range(10):
        results = run_campaign(OracleAgent, seed, months=4, k=5)
        assert all(r.scorecard.final_score == 1.0 for r in results)
        assert all(r.drift_accounts == 0 for r in results)


def test_flawed_agent_drifts_and_does_not_recover():
    # With k=5 every month seeds an accrual, which the baseline never books, so it
    # must fail from month 1 and the drift must never return to zero.
    results = run_campaign(BaselineAgent, seed=1, months=4, k=5)
    assert results[0].scorecard.bs_recon is False
    drifts = [r.drift_accounts for r in results]
    assert drifts[0] > 0
    assert all(d > 0 for d in drifts)            # never recovers
    assert drifts == sorted(drifts)              # drift is non-decreasing (compounding)


def test_campaign_ground_truth_chain_is_consistent():
    # Every month's generation self-checks (replay(opening, gold) == gold_final)
    # still hold when built on a carried opening — run_campaign would raise otherwise.
    run_campaign(OracleAgent, seed=3, months=5, k=4)
