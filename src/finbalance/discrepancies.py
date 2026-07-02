"""Discrepancy taxonomy and seeding (bottom-up, evidence-bearing).

Each seeder contributes to *two* worlds and returns a :class:`SeedResult`:

* ``correct_entries`` — the journal entries a perfect accountant would have booked.
* ``asbooked_entries`` — what the company actually recorded (with the error).
* ``docs`` — any extra evidence document (e.g. a post-close vendor invoice).
* ``discrepancy`` — the record, including the gold correcting entry.

The generator posts ``correct_entries`` to get ``gold_final_balances`` and
``asbooked_entries`` to get the public opening trial balance, then asserts that
replaying the gold entries turns one into the other. Because the error now lives
in the *documents* (a duplicated GL line, a transposed amount, a fee that is on
the bank but not in the ledger), a real agent can actually discover it — not just
infer it from balance math.

Entry-id discipline: an entry present in both worlds (possibly with a different
amount, as in a transposition) keeps the **same** ``entry_id`` in both, so the
bank statement (rendered from the correct world) can be tied back to the ledger
line by ``ext_ref``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from . import coa as C
from .model import (
    DiscrepancyKind,
    JournalEntry,
    JournalLine,
    SeededDiscrepancy,
    Statement,
    StatementLine,
)
from .money import Cents


@dataclass
class GenContext:
    period_end: str
    rng: Random
    counter: int = 0
    dit_entry_ids: set = field(default_factory=set)
    used_amounts: set = field(default_factory=set)
    dit_amount: "Cents | None" = None

    def eid(self, prefix: str = "gl") -> str:
        self.counter += 1
        return f"{prefix}{self.counter:03d}"

    def amount(self, lo: int, hi: int) -> Cents:
        """Draw a cent amount unique within this instance (aids matching + DIT)."""
        for _ in range(200):
            a = self.rng.randrange(lo, hi)
            if a not in self.used_amounts:
                self.used_amounts.add(a)
                return a
        self.used_amounts.add(a)
        return a


@dataclass
class SeedResult:
    discrepancy: SeededDiscrepancy
    correct_entries: list = field(default_factory=list)
    asbooked_entries: list = field(default_factory=list)
    docs: list = field(default_factory=list)


def _entry(eid: str, period_end: str, memo: str, *lines: JournalLine, source: str = "GL") -> JournalEntry:
    return JournalEntry(entry_id=eid, date=period_end, memo=memo, lines=tuple(lines), source=source)


def _adj(eid: str, period_end: str, memo: str, *lines: JournalLine) -> JournalEntry:
    return _entry(eid, period_end, memo, *lines, source="ADJ")


# --------------------------------------------------------------------------- #
# Base activity: identical in both worlds, never corrupted.
# --------------------------------------------------------------------------- #


def build_base_activity(ctx: GenContext) -> list[JournalEntry]:
    pe = ctx.period_end
    cap = ctx.amount(4_000_00, 6_000_00)
    eq = ctx.amount(1_200_00, 3_600_00)
    cash_sales = ctx.amount(4_000_00, 9_000_00)
    ar_sales = ctx.amount(1_500_00, 4_000_00)
    op_cash = ctx.amount(1_000_00, 3_000_00)
    prepaid = ctx.amount(300_00, 1_200_00)
    depr = ctx.amount(100_00, 400_00)
    sales_tax = ctx.amount(50_00, 400_00)
    return [
        _entry(ctx.eid(), pe, "Owner capital contribution",
               JournalLine(C.CASH, debit=cap), JournalLine(C.COMMON_STOCK, credit=cap)),
        _entry(ctx.eid(), pe, "Purchase equipment",
               JournalLine(C.EQUIPMENT, debit=eq), JournalLine(C.CASH, credit=eq)),
        _entry(ctx.eid(), pe, "Cash sales",
               JournalLine(C.CASH, debit=cash_sales), JournalLine(C.REVENUE, credit=cash_sales)),
        _entry(ctx.eid(), pe, "Sales on account",
               JournalLine(C.AR, debit=ar_sales), JournalLine(C.REVENUE, credit=ar_sales)),
        _entry(ctx.eid(), pe, "Operating expenses paid in cash",
               JournalLine(C.OP_EXPENSE, debit=op_cash), JournalLine(C.CASH, credit=op_cash)),
        _entry(ctx.eid(), pe, "Prepay insurance",
               JournalLine(C.PREPAID, debit=prepaid), JournalLine(C.CASH, credit=prepaid)),
        _entry(ctx.eid(), pe, "Monthly depreciation",
               JournalLine(C.OP_EXPENSE, debit=depr), JournalLine(C.ACCUM_DEPR, credit=depr)),
        _entry(ctx.eid(), pe, "Collect sales tax",
               JournalLine(C.CASH, debit=sales_tax), JournalLine(C.SALES_TAX, credit=sales_tax)),
    ]


# --------------------------------------------------------------------------- #
# Seeders. Each owns its correct/as-booked/gold triple + evidence.
# --------------------------------------------------------------------------- #


def seed_unrecorded_bank_fee(ctx: GenContext) -> SeedResult:
    pe, fee = ctx.period_end, ctx.amount(15_00, 60_00)
    eid = ctx.eid("fee")
    correct = _entry(eid, pe, "Bank service charge",
                     JournalLine(C.BANK_FEES, debit=fee), JournalLine(C.CASH, credit=fee))
    disc_id = ctx.eid("disc")
    gold = _adj(f"gold-{disc_id}", pe, "Record bank service charge",
                JournalLine(C.BANK_FEES, debit=fee), JournalLine(C.CASH, credit=fee))
    d = SeededDiscrepancy(
        disc_id=disc_id, kind=DiscrepancyKind.UNRECORDED_BANK_FEE, requires_adjustment=True,
        affected_accounts=(C.CASH, C.BANK_FEES), gold_entry=gold,
        detection_hint="A bank service charge appears on the statement but not in the ledger.",
    )
    # Present on the bank (correct world has the cash entry) but omitted from the
    # public ledger (as-booked contributes nothing).
    return SeedResult(discrepancy=d, correct_entries=[correct], asbooked_entries=[])


def seed_missing_accrual(ctx: GenContext) -> SeedResult:
    pe, amt = ctx.period_end, ctx.amount(400_00, 1_500_00)
    eid = ctx.eid("acc")
    correct = _entry(eid, pe, "Accrue unbilled utilities",
                     JournalLine(C.OP_EXPENSE, debit=amt), JournalLine(C.ACCRUED_LIAB, credit=amt))
    disc_id = ctx.eid("disc")
    gold = _adj(f"gold-{disc_id}", pe, "Accrue unbilled operating expense",
                JournalLine(C.OP_EXPENSE, debit=amt), JournalLine(C.ACCRUED_LIAB, credit=amt))
    invoice = Statement(
        kind="post_close_invoice", account_code=C.ACCRUED_LIAB, opening_balance=0, closing_balance=amt,
        lines=(StatementLine(f"inv-{disc_id}", pe,
                             "Vendor invoice for January utilities, received after month-end", amt,
                             ext_ref="ACCRUAL"),),
    )
    d = SeededDiscrepancy(
        disc_id=disc_id, kind=DiscrepancyKind.MISSING_ACCRUAL, requires_adjustment=True,
        affected_accounts=(C.OP_EXPENSE, C.ACCRUED_LIAB), gold_entry=gold,
        detection_hint="An incurred but unbilled expense (see post-close invoice) was not accrued.",
    )
    return SeedResult(discrepancy=d, correct_entries=[correct], asbooked_entries=[], docs=[invoice])


def seed_duplicate_entry(ctx: GenContext) -> SeedResult:
    pe, amt = ctx.period_end, ctx.amount(300_00, 1_200_00)
    eid = ctx.eid("bill")
    bill = _entry(eid, pe, "Vendor bill - office supplies",
                  JournalLine(C.OP_EXPENSE, debit=amt), JournalLine(C.AP, credit=amt))
    dup = _entry(ctx.eid("bill"), pe, "Vendor bill - office supplies",  # same memo+amount, new id
                 JournalLine(C.OP_EXPENSE, debit=amt), JournalLine(C.AP, credit=amt))
    disc_id = ctx.eid("disc")
    gold = _adj(f"gold-{disc_id}", pe, "Reverse duplicated vendor bill",
                JournalLine(C.AP, debit=amt), JournalLine(C.OP_EXPENSE, credit=amt))
    d = SeededDiscrepancy(
        disc_id=disc_id, kind=DiscrepancyKind.DUPLICATE_ENTRY, requires_adjustment=True,
        affected_accounts=(C.OP_EXPENSE, C.AP), gold_entry=gold,
        detection_hint="The same vendor bill appears twice in the ledger; reverse one.",
    )
    # Correct world books the bill once; the company booked it twice.
    return SeedResult(discrepancy=d, correct_entries=[bill], asbooked_entries=[bill, dup])


def seed_transposition_error(ctx: GenContext) -> SeedResult:
    pe = ctx.period_end
    correct_amt = ctx.rng.choice([5_400_00, 3_200_00, 8_100_00, 2_500_00, 6_300_00])
    transposed = _transpose(correct_amt, ctx.rng)
    if transposed == correct_amt:
        transposed = correct_amt - 90_00  # guarantee a nonzero delta
    delta = correct_amt - transposed
    # Reserve these amounts so the later-drawn DIT can't collide with the gold
    # cash adjustment (keeps the timing-trap detector unambiguous).
    ctx.used_amounts.update({correct_amt, transposed, abs(delta)})
    eid = ctx.eid("rev")
    correct = _entry(eid, pe, "Customer payment received",
                     JournalLine(C.CASH, debit=correct_amt), JournalLine(C.REVENUE, credit=correct_amt))
    asbooked = _entry(eid, pe, "Customer payment received",  # SAME id, transposed amount
                      JournalLine(C.CASH, debit=transposed), JournalLine(C.REVENUE, credit=transposed))
    disc_id = ctx.eid("disc")
    if delta >= 0:
        gold = _adj(f"gold-{disc_id}", pe, "Correct transposed customer payment",
                    JournalLine(C.CASH, debit=delta), JournalLine(C.REVENUE, credit=delta))
    else:
        gold = _adj(f"gold-{disc_id}", pe, "Correct transposed customer payment",
                    JournalLine(C.REVENUE, debit=-delta), JournalLine(C.CASH, credit=-delta))
    d = SeededDiscrepancy(
        disc_id=disc_id, kind=DiscrepancyKind.TRANSPOSITION_ERROR, requires_adjustment=True,
        affected_accounts=(C.CASH, C.REVENUE), gold_entry=gold,
        detection_hint=f"A payment was booked as {transposed} but the bank shows {correct_amt}.",
    )
    return SeedResult(discrepancy=d, correct_entries=[correct], asbooked_entries=[asbooked])


def seed_misclassification(ctx: GenContext) -> SeedResult:
    pe, amt = ctx.period_end, ctx.amount(200_00, 900_00)
    eid = ctx.eid("chg")
    correct = _entry(eid, pe, "Bank service charge",  # memo signals it IS a bank fee
                     JournalLine(C.BANK_FEES, debit=amt), JournalLine(C.CASH, credit=amt))
    asbooked = _entry(eid, pe, "Bank service charge",  # same memo, wrong debit account
                      JournalLine(C.OP_EXPENSE, debit=amt), JournalLine(C.CASH, credit=amt))
    disc_id = ctx.eid("disc")
    gold = _adj(f"gold-{disc_id}", pe, "Reclassify bank fee out of operating expenses",
                JournalLine(C.BANK_FEES, debit=amt), JournalLine(C.OP_EXPENSE, credit=amt))
    d = SeededDiscrepancy(
        disc_id=disc_id, kind=DiscrepancyKind.MISCLASSIFICATION, requires_adjustment=True,
        affected_accounts=(C.OP_EXPENSE, C.BANK_FEES), gold_entry=gold,
        detection_hint="A charge memo'd 'Bank service charge' was debited to Operating Expenses.",
    )
    return SeedResult(discrepancy=d, correct_entries=[correct], asbooked_entries=[asbooked])


def seed_timing_difference(ctx: GenContext) -> SeedResult:
    pe = ctx.period_end
    dit = ctx.amount(500_00, 2_000_00)
    ctx.dit_amount = dit
    eid = ctx.eid("dit")
    ctx.dit_entry_ids.add(eid)
    deposit = _entry(eid, pe, "Late-month customer deposit",
                     JournalLine(C.CASH, debit=dit), JournalLine(C.REVENUE, credit=dit))
    disc_id = ctx.eid("disc")
    d = SeededDiscrepancy(
        disc_id=disc_id, kind=DiscrepancyKind.TIMING_DIFFERENCE_NOADJUST, requires_adjustment=False,
        affected_accounts=(C.CASH,), gold_entry=None,
        detection_hint=(f"A deposit of {dit} cents is in the ledger but not yet on the bank "
                        "statement — a deposit in transit. Do NOT adjust; disclose as reconciling item."),
    )
    # Correctly booked in BOTH worlds; only the bank statement omits it.
    return SeedResult(discrepancy=d, correct_entries=[deposit], asbooked_entries=[deposit])


_SEEDERS = {
    DiscrepancyKind.UNRECORDED_BANK_FEE: seed_unrecorded_bank_fee,
    DiscrepancyKind.MISSING_ACCRUAL: seed_missing_accrual,
    DiscrepancyKind.DUPLICATE_ENTRY: seed_duplicate_entry,
    DiscrepancyKind.TRANSPOSITION_ERROR: seed_transposition_error,
    DiscrepancyKind.MISCLASSIFICATION: seed_misclassification,
}


def seed_discrepancies(ctx: GenContext, k: int) -> list[SeedResult]:
    """Seed ``k`` book-error discrepancies plus the mandatory timing trap."""
    kinds = list(_SEEDERS)
    ctx.rng.shuffle(kinds)
    chosen = kinds[: max(0, min(k, len(kinds)))]
    results = [_SEEDERS[kind](ctx) for kind in chosen]
    results.append(seed_timing_difference(ctx))
    return results


def _transpose(value_cents: Cents, rng: Random) -> Cents:
    dollars = value_cents // 100
    s = list(str(dollars))
    if len(s) < 2:
        return value_cents
    i = rng.randrange(len(s) - 1)
    s[i], s[i + 1] = s[i + 1], s[i]
    return int("".join(s)) * 100 + (value_cents % 100)
