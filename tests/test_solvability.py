"""Every seeded error must leave discoverable evidence in the PUBLIC instance.

This is the audit that closes the v1 "solvability gap": a real agent, seeing only
the general ledger + statements (never ground truth), has enough evidence to find
each discrepancy.
"""

from __future__ import annotations

from finbalance import coa as C
from finbalance.generator import generate_instance
from finbalance.model import DiscrepancyKind


def _bank(inst):
    return next(s for s in inst.statements if s.kind == "bank")


def _gl_ids(inst):
    return {e.entry_id for e in inst.general_ledger}


def _cash_amount(entry):
    return sum(l.debit - l.credit for l in entry.lines if l.account == C.CASH)


def test_all_kinds_have_evidence_across_seeds():
    for seed in range(100):
        inst, gt = generate_instance(seed, k=6)  # k=6 → all six book errors present
        kinds = {d.kind for d in gt.discrepancies}
        gl = inst.general_ledger
        bank = _bank(inst)
        gl_ids = _gl_ids(inst)
        bank_refs = {l.ext_ref for l in bank.lines}

        # DUPLICATE: the vendor bill appears twice in the ledger.
        if DiscrepancyKind.DUPLICATE_ENTRY in kinds:
            bills = [e for e in gl if e.memo.startswith("Vendor bill")]
            assert len(bills) == 2, f"seed {seed}: expected duplicate bill, got {len(bills)}"

        # UNRECORDED_BANK_FEE: a bank line with no matching ledger entry.
        if DiscrepancyKind.UNRECORDED_BANK_FEE in kinds:
            assert any(l.ext_ref not in gl_ids and l.amount < 0 for l in bank.lines), \
                f"seed {seed}: no unrecorded bank fee on statement"

        # TRANSPOSITION: a ledger cash entry whose amount disagrees with its bank line.
        if DiscrepancyKind.TRANSPOSITION_ERROR in kinds:
            by_id = {e.entry_id: e for e in gl}
            mismatched = [
                l for l in bank.lines
                if l.ext_ref in by_id and _cash_amount(by_id[l.ext_ref]) != l.amount
            ]
            assert mismatched, f"seed {seed}: no transposition mismatch between GL and bank"

        # MISCLASSIFICATION: a 'Bank service charge' entry debited to Operating Expenses.
        if DiscrepancyKind.MISCLASSIFICATION in kinds:
            assert any(
                e.memo == "Bank service charge" and any(l.account == C.OP_EXPENSE and l.debit for l in e.lines)
                for e in gl
            ), f"seed {seed}: no misclassified bank charge in GL"

        # MISSING_ACCRUAL: a post-close invoice document is present.
        if DiscrepancyKind.MISSING_ACCRUAL in kinds:
            assert any(s.kind == "post_close_invoice" for s in inst.statements), \
                f"seed {seed}: no post-close invoice evidence"

        # NSF CHECK: a returned-check line on the bank with no matching GL entry.
        if DiscrepancyKind.NSF_CHECK in kinds:
            assert any(l.ext_ref not in gl_ids and "NSF" in l.description for l in bank.lines), \
                f"seed {seed}: no NSF return evidence on statement"

        # TIMING TRAP: a ledger cash deposit that is NOT on the bank statement.
        cash_entries = [e for e in gl if any(l.account == C.CASH for l in e.lines)]
        assert any(e.entry_id not in bank_refs for e in cash_entries), \
            f"seed {seed}: deposit-in-transit not distinguishable"

        # PROVENANCE: every discrepancy cites its real-world source.
        assert all(d.provenance for d in gt.discrepancies), \
            f"seed {seed}: discrepancy missing provenance"


def test_timing_trap_amount_is_unique():
    for seed in range(100):
        inst, gt = generate_instance(seed, k=6)
        # No other ledger entry moves cash by exactly the DIT amount, so a trap
        # violation can be detected unambiguously (Phase C).
        dit = gt.timing_trap_amount
        assert dit is not None
        cash_moves = [abs(_cash_amount(e)) for e in inst.general_ledger
                      if any(l.account == C.CASH for l in e.lines)]
        assert cash_moves.count(dit) == 1, f"seed {seed}: DIT amount not unique"
