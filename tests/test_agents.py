"""Gate 3b: end-to-end through the harness — oracle == 1.0, null low."""

from __future__ import annotations

from finbalance.agents import BaselineAgent, NullAgent, OracleAgent, SloppyAgent
from finbalance.generator import generate_instance
from finbalance.harness import AgentSession
from finbalance.verifier import score


def _run(agent, seed, k=4):
    inst, gt = generate_instance(seed, k=k)
    sub = agent.run(AgentSession(inst), gt)
    return score(inst, gt, sub), inst, gt


def test_oracle_scores_one_across_seeds():
    for seed in range(50):
        sc, _, _ = _run(OracleAgent(), seed)
        assert sc.final_score == 1.0, f"seed {seed}: {sc.final_score}"


def test_null_scores_low_across_seeds():
    for seed in range(50):
        sc, _, _ = _run(NullAgent(), seed)
        assert sc.final_score < 0.5
        assert not sc.bs_recon


def test_oracle_trace_is_recorded():
    sc, _, _ = _run(OracleAgent(), 1)
    assert sc.tool_calls >= 1  # posted at least one gold adjustment via the tool


def test_metric_has_midscale_resolution():
    """Baseline (tools only, no ground truth) must land strictly between null and
    oracle, and its per-type breakdown must show a real blind spot."""
    for seed in range(30):
        oracle, _, _ = _run(OracleAgent(), seed, k=5)
        baseline, _, gt = _run(BaselineAgent(), seed, k=5)
        null, _, _ = _run(NullAgent(), seed, k=5)
        assert null.final_score < baseline.final_score < oracle.final_score == 1.0
        # Baseline catches the cash/statement-driven errors...
        assert baseline.caught_by_kind["unrecorded_bank_fee"]
        assert baseline.caught_by_kind["transposition_error"]
        assert baseline.caught_by_kind["duplicate_entry"]
        # ...but is blind to policy-driven accruals (its documented blind spot).
        assert not baseline.caught_by_kind["missing_accrual"]
        assert baseline.timing_trap_respected  # correctly leaves the DIT alone


def test_sloppy_agent_is_gated_to_zero():
    for seed in range(30):
        sc, _, _ = _run(SloppyAgent(), seed, k=5)
        assert sc.unauthorized_change is True
        assert sc.final_score == 0.0
        assert sc.raw_score > 0.0  # the gate, not a low raw score, is what zeroes it


def test_baseline_never_trips_a_gate():
    for seed in range(30):
        sc, _, _ = _run(BaselineAgent(), seed, k=5)
        assert not sc.forbidden_touch and not sc.unauthorized_change
