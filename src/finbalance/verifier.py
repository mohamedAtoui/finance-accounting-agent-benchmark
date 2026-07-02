"""Deterministic verifier: metrics, partial credit, and hard gates.

The core score is entirely programmatic — no LLM judge. Correctness is judged on
the *balances that result from replaying the agent's entries*, never on matching
the agent's specific journal-entry text. Any set of entries that lands the gold
balances passes, so alternative-but-correct codings are accepted for free.

Metrics (all in [0, 1] unless noted):

* ``bs_recon`` — replay the agent's entries from the opening TB; do ALL accounts
  match gold within $0.01? This is the honest headline metric.
* ``bs_exact`` — does the agent's *self-reported* balance sheet match gold? Catches
  agents whose narrative disagrees with the entries they actually posted.
* ``accounts_reconciled`` — fraction of reconcilable accounts matching gold.
* ``discrepancies_caught`` — fraction of book-error discrepancies whose affected
  accounts all match gold after replay.
* ``timing_trap_respected`` — did Cash land on gold (i.e. the agent booked the
  real cash adjustments but did NOT invent an entry for the deposit in transit)?

Hard gates (either → final score 0.0), mirroring AppWorld's allowed/forbidden
delta model and CFAgentBench's money-movement gates:

* ``forbidden_touch`` — a protected account's balance changed.
* ``unauthorized_change`` — an account that had no legitimate reason to change
  (``gold == opening``) was nonetheless moved.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ledger import replay
from .model import GroundTruth, Instance
from .money import Cents, within_tolerance

WEIGHTS = {"bs_recon": 0.60, "discrepancies_caught": 0.25, "accounts_reconciled": 0.15}
TOL_CENTS = 1  # $0.01


@dataclass(frozen=True)
class Submission:
    entries: tuple
    reported_bs: dict          # code -> Cents (agent's self-reported balances)
    trace: tuple = ()          # recorded tool calls, for efficiency


@dataclass
class Scorecard:
    instance_id: str
    bs_exact: bool
    bs_recon: bool
    accounts_reconciled: float
    discrepancies_caught: float
    timing_trap_respected: bool
    forbidden_touch: bool
    unauthorized_change: bool
    rejected_entries: int
    tool_calls: int
    efficiency: float
    raw_score: float
    final_score: float
    caught_by_kind: dict = None  # DiscrepancyKind.value -> bool (per-type reporting)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def score(instance: Instance, gt: GroundTruth, submission: Submission) -> Scorecard:
    opening = instance.opening_trial_balance
    gold = gt.gold_final_balances
    result = replay(instance.chart_of_accounts, opening, submission.entries)
    final = result.final

    def matches_gold(code: str) -> bool:
        return within_tolerance(final.get(code, 0), gold[code], TOL_CENTS)

    # --- headline + partial credit -------------------------------------------
    bs_recon = all(matches_gold(c) for c in gold)
    bs_exact = all(
        within_tolerance(submission.reported_bs.get(c, _MISSING), gold[c], TOL_CENTS)
        for c in gold
    )

    recon_accts = sorted(gt.reconcilable_accounts)
    accounts_reconciled = _frac(sum(matches_gold(c) for c in recon_accts), len(recon_accts))

    from . import coa as C

    # Per-type "caught" is a DIAGNOSTIC judged by whether the agent posted the
    # canonical correcting move for that error (effect-vector match against the
    # gold entry). Unlike an absolute balance match, this is isolated — one
    # uncaught error does not poison another that happens to share an account
    # (e.g. Operating Expenses). The headline score below stays balance-based.
    agent_effects = [_effect_map(e) for e in submission.entries]
    book_errors = [d for d in gt.discrepancies if d.requires_adjustment]
    caught_by_kind = {
        d.kind.value: (d.gold_entry is not None
                       and _effect_map(d.gold_entry) in agent_effects)
        for d in book_errors
    }
    caught = sum(caught_by_kind.values())
    discrepancies_caught = _frac(caught, len(book_errors))

    # Timing trap (independent of the cash balance): the agent must NOT book any
    # entry that moves cash by the deposit-in-transit amount. That amount is unique
    # per instance, so a violation is detected unambiguously.
    dit = gt.timing_trap_amount
    def _net_cash(entry) -> int:
        return sum(l.debit - l.credit for l in entry.lines if l.account == C.CASH)
    timing_trap_respected = True
    if dit is not None:
        timing_trap_respected = not any(abs(_net_cash(e)) == dit for e in submission.entries)

    # --- gates ---------------------------------------------------------------
    legit_change = {c for c in gold if not within_tolerance(gold[c], opening.get(c, 0), 0)}
    forbidden_touch = any(
        not within_tolerance(final.get(c, 0), opening.get(c, 0), 0)
        for c in gt.protected_accounts
    )
    unauthorized_change = any(
        c not in legit_change and not within_tolerance(final.get(c, 0), opening.get(c, 0), 0)
        for c in gold
    )

    # --- aggregate -----------------------------------------------------------
    raw = (
        WEIGHTS["bs_recon"] * (1.0 if bs_recon else 0.0)
        + WEIGHTS["discrepancies_caught"] * discrepancies_caught
        + WEIGHTS["accounts_reconciled"] * accounts_reconciled
    )
    gated = 0.0 if (forbidden_touch or unauthorized_change) else raw

    tool_calls = len(submission.trace)
    efficiency = round(caught / tool_calls, 3) if tool_calls else 0.0

    return Scorecard(
        instance_id=instance.instance_id,
        bs_exact=bs_exact,
        bs_recon=bs_recon,
        accounts_reconciled=round(accounts_reconciled, 3),
        discrepancies_caught=round(discrepancies_caught, 3),
        timing_trap_respected=timing_trap_respected,
        forbidden_touch=forbidden_touch,
        unauthorized_change=unauthorized_change,
        rejected_entries=len(result.rejected),
        tool_calls=tool_calls,
        efficiency=efficiency,
        raw_score=round(raw, 3),
        final_score=round(gated, 3),
        caught_by_kind=caught_by_kind,
    )


_MISSING = 1 << 40  # a value no real balance will equal, so a missing report fails


def _effect_map(entry) -> tuple:
    """Canonical (account -> debit−credit) effect of an entry, zeros dropped.

    Two entries with the same effect map are equivalent corrections. Returned as a
    sorted tuple of items so it is hashable and comparable.
    """
    acc: dict = {}
    for line in entry.lines:
        acc[line.account] = acc.get(line.account, 0) + line.debit - line.credit
    return tuple(sorted((a, v) for a, v in acc.items() if v != 0))


def _frac(num: int, den: int) -> float:
    return 1.0 if den == 0 else num / den
