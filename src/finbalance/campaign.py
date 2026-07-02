"""Multi-month campaigns: the long-horizon, compounding-error dimension.

Each month is generated on top of the *previous month's closing balances*. The
ground-truth chain carries the clean gold balances forward; the agent chain
carries the **agent's own submitted balances** forward. That is what makes errors
compound: an uncaught adjustment in month 1 corrupts the opening position of every
later month, and ordinary within-month reconciliation cannot recover it — exactly
the degradation observed in real month-over-month closes.

A perfect agent stays at 1.0 every month; a flawed agent drifts and never
recovers, which the per-month score and the account-drift count both show.
"""

from __future__ import annotations

from dataclasses import dataclass

from .generator import generate_instance
from .harness import AgentSession
from .ledger import replay
from .money import within_tolerance
from .verifier import Scorecard, score


@dataclass
class MonthResult:
    month: int
    scorecard: Scorecard
    drift_accounts: int  # accounts where the agent's carried close != gold close


def run_campaign(agent_factory, seed: int, months: int = 3, k: int = 4) -> list[MonthResult]:
    results: list[MonthResult] = []
    agent_carry: "dict | None" = None
    gold_carry: "dict | None" = None

    for m in range(months):
        month_seed = seed * 1000 + m  # fresh discrepancies each month
        # Ground-truth instance on the clean chain (authoritative gold).
        _inst_g, gt = generate_instance(month_seed, k=k, opening_balances=gold_carry,
                                        instance_id=f"m{m + 1}")
        # The instance as the agent experiences it, starting from ITS carried books.
        inst_a, _gt_a = generate_instance(month_seed, k=k, opening_balances=agent_carry,
                                          instance_id=f"m{m + 1}")

        sub = agent_factory().run(AgentSession(inst_a), gt)
        sc = score(inst_a, gt, sub)

        # Agent's actual closing position (replay its entries from ITS opening).
        agent_close = replay(inst_a.chart_of_accounts, inst_a.opening_trial_balance, sub.entries).final
        gold_close = gt.gold_final_balances
        drift = sum(1 for c in gold_close if not within_tolerance(agent_close.get(c, 0), gold_close[c], 1))

        results.append(MonthResult(month=m + 1, scorecard=sc, drift_accounts=drift))
        agent_carry = agent_close   # <-- the agent lives with its own mistakes
        gold_carry = gold_close

    return results


def format_campaign(agent_name: str, results: list[MonthResult]) -> str:
    lines = [
        f"Campaign: agent={agent_name}  months={len(results)}",
        "-" * 44,
        f"{'month':<8}{'final':>10}{'BSrecon':>10}{'drift':>10}",
    ]
    for r in results:
        lines.append(
            f"{r.month:<8}{r.scorecard.final_score:>10.2f}"
            f"{('PASS' if r.scorecard.bs_recon else 'FAIL'):>10}{r.drift_accounts:>10}"
        )
    trend = " → ".join(f"{r.scorecard.final_score:.2f}" for r in results)
    lines += ["-" * 44, f"score trajectory: {trend}"]
    return "\n".join(lines)
