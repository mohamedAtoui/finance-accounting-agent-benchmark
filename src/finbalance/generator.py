"""Procedural generator: one synthetic "company-month" per seed (bottom-up).

Pipeline:

1. Build base activity (identical in both worlds) plus, per seeded discrepancy, a
   ``correct``-world entry set and an ``as-booked`` entry set that differ exactly
   by that error (a duplicated line, a transposed amount, an omitted fee, ...).
2. Post the correct entries → ``gold_final_balances`` (the answer key). Post the
   as-booked entries → the **public** opening trial balance the agent starts from.
3. The public general ledger the agent reads IS the as-booked entry set, so the
   evidence for every error is visible in the documents — not just implied by
   balance math.
4. Assert the invariants: replaying the gold adjustments from the opening
   reproduces ``gold_final_balances`` exactly, and both trial balances net to
   zero. A broken discrepancy can never ship.

The bank statement is rendered from the *correct* cash entries (the bank knows the
truth), omitting the deposit in transit and naturally including the unbooked fee —
so the bank reconciliation is genuinely tie-able.
"""

from __future__ import annotations

from random import Random

from . import coa as C
from .discrepancies import GenContext, build_base_activity, seed_discrepancies
from .ledger import Ledger, replay
from .model import (
    Account,
    GroundTruth,
    Instance,
    JournalEntry,
    Statement,
    StatementLine,
)
from .money import Cents

PERIOD_END = "2025-01-31"


def _balances_from(coa: tuple[Account, ...], entries: list[JournalEntry],
                   start: "dict[str, Cents] | None") -> dict[str, Cents]:
    led = Ledger(coa, dict(start or {}))
    for e in entries:
        led.post(e)
    return led.balances()


def generate_instance(
    seed: int, k: int = 4, opening_balances: "dict[str, Cents] | None" = None,
    period_end: str = PERIOD_END, instance_id: "str | None" = None,
) -> tuple[Instance, GroundTruth]:
    rng = Random(seed)
    coa = C.build_chart_of_accounts()
    ctx = GenContext(period_end, rng)

    base = build_base_activity(ctx)
    correct_entries: list[JournalEntry] = list(base)
    asbooked_entries: list[JournalEntry] = list(base)
    docs: list[Statement] = []
    discrepancies = []
    for res in seed_discrepancies(ctx, k):
        correct_entries += res.correct_entries
        asbooked_entries += res.asbooked_entries
        docs += res.docs
        discrepancies.append(res.discrepancy)

    clean_final = _balances_from(coa, correct_entries, opening_balances)
    opening = _balances_from(coa, asbooked_entries, opening_balances)
    gold_adjustments = tuple(d.gold_entry for d in discrepancies if d.gold_entry is not None)

    # Invariants — the proof that ground truth is correct by construction.
    replayed = replay(coa, opening, gold_adjustments)
    assert replayed.rejected == (), f"gold adjustments rejected: {replayed.rejected}"
    assert replayed.final == clean_final, "replay(opening, gold) != clean_final"
    assert Ledger(coa, opening).trial_balance_check() == 0, "opening TB does not balance"
    assert Ledger(coa, clean_final).trial_balance_check() == 0, "final TB does not balance"

    start_cash = (opening_balances or {}).get(C.CASH, 0)
    statements = _build_statements(coa, correct_entries, clean_final, ctx, docs, start_cash)

    instance = Instance(
        instance_id=instance_id or f"seed-{seed:04d}",
        seed=seed,
        chart_of_accounts=coa,
        opening_trial_balance=opening,
        general_ledger=tuple(asbooked_entries),
        statements=statements,
        policy=C.build_policy(period_end),
    )
    gt = GroundTruth(
        gold_adjustments=gold_adjustments,
        gold_final_balances=clean_final,
        discrepancies=tuple(discrepancies),
        protected_accounts=frozenset(a.code for a in coa if a.protected),
        reconcilable_accounts=frozenset(a.code for a in coa if a.reconcilable),
        timing_trap_amount=ctx.dit_amount,
    )
    return instance, gt


def _build_statements(
    coa: tuple[Account, ...],
    correct_entries: list[JournalEntry],
    clean_final: dict[str, Cents],
    ctx: GenContext,
    docs: list[Statement],
    start_cash: Cents = 0,
) -> tuple[Statement, ...]:
    """Bank statement rendered from the true (correct) cash entries.

    Every correct cash movement becomes a bank line tagged with its ledger
    ``entry_id`` (so it can be tied back), EXCEPT the deposit in transit, which
    has not yet cleared. The unbooked bank fee appears here naturally because it
    is a correct-world cash entry with no matching public ledger entry. The
    statement opens at ``start_cash`` (the prior period's cleared balance).
    """
    pe = ctx.period_end
    bank_lines: list[StatementLine] = []
    running = start_cash
    for e in correct_entries:
        if e.entry_id in ctx.dit_entry_ids:
            continue  # deposit in transit: on the books, not yet on the statement
        for line in e.lines:
            if line.account == C.CASH:
                amt = line.debit - line.credit
                running += amt
                bank_lines.append(
                    StatementLine(f"bnk-{e.entry_id}", pe, e.memo, amt, ext_ref=e.entry_id)
                )
    bank_closing = running
    assert bank_closing == clean_final[C.CASH] - (ctx.dit_amount or 0), "bank statement mis-ties"

    bank = Statement(kind="bank", account_code=C.CASH, opening_balance=start_cash,
                     closing_balance=bank_closing, lines=tuple(bank_lines))
    ar = Statement(kind="ar_subledger", account_code=C.AR, opening_balance=0,
                   closing_balance=clean_final[C.AR],
                   lines=(StatementLine("ar-001", pe, "Open customer invoices", clean_final[C.AR]),))
    ap = Statement(kind="ap_subledger", account_code=C.AP, opening_balance=0,
                   closing_balance=clean_final[C.AP],
                   lines=(StatementLine("ap-001", pe, "Open vendor bills (per vendor statements)",
                                        clean_final[C.AP]),))
    return (bank, ar, ap) + tuple(docs)
