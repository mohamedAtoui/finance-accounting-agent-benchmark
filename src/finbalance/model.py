"""Core data structures for the reconciliation benchmark.

Two worlds live here:

* The **public** :class:`Instance` — everything the agent is allowed to see
  (chart of accounts, opening trial balance, general ledger, external
  statements, policy sheet).
* The **hidden** :class:`GroundTruth` — the computable answer key produced by the
  generator (gold adjusting entries, the authoritative post-close balances, and
  the seeded-discrepancy records used for partial credit).

All amounts are integer cents (see :mod:`finbalance.money`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .money import Cents


class Side(Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class AcctType(Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


# Normal balance side per account type. Contra accounts override this explicitly
# (e.g. Accumulated Depreciation is an ASSET carried on the CREDIT side).
NORMAL_SIDE: dict[AcctType, Side] = {
    AcctType.ASSET: Side.DEBIT,
    AcctType.EXPENSE: Side.DEBIT,
    AcctType.LIABILITY: Side.CREDIT,
    AcctType.EQUITY: Side.CREDIT,
    AcctType.REVENUE: Side.CREDIT,
}


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    type: AcctType
    normal_side: Side
    reconcilable: bool = False  # has an external statement to tie to
    protected: bool = False     # forbidden-delta guard: agent must not change


@dataclass(frozen=True)
class JournalLine:
    account: str
    debit: Cents = 0
    credit: Cents = 0

    def __post_init__(self) -> None:
        if self.debit < 0 or self.credit < 0:
            raise ValueError("journal line amounts must be non-negative")
        if self.debit and self.credit:
            raise ValueError("a journal line has either a debit or a credit, not both")


@dataclass(frozen=True)
class JournalEntry:
    entry_id: str
    date: str  # ISO date
    memo: str
    lines: tuple[JournalLine, ...]
    source: str = "GL"  # "GL" | "ADJ" | "AGENT"

    def total_debit(self) -> Cents:
        return sum(l.debit for l in self.lines)

    def total_credit(self) -> Cents:
        return sum(l.credit for l in self.lines)

    def is_balanced(self) -> bool:
        return self.total_debit() == self.total_credit()


@dataclass(frozen=True)
class StatementLine:
    line_id: str
    date: str
    description: str
    amount: Cents            # signed, from the statement's point of view
    ext_ref: "str | None" = None  # e.g. check number, for matching


@dataclass(frozen=True)
class Statement:
    kind: str                # "bank" | "ar_subledger" | "ap_subledger" | "credit_card"
    account_code: str        # GL account this statement reconciles to
    opening_balance: Cents
    closing_balance: Cents
    lines: tuple[StatementLine, ...]

    @property
    def doc_id(self) -> str:
        return f"stmt::{self.kind}::{self.account_code}"


@dataclass(frozen=True)
class PolicySheet:
    period_end: str
    materiality_cents: Cents
    accrual_rules: tuple[str, ...]
    protected_accounts: tuple[str, ...]

    @property
    def doc_id(self) -> str:
        return "policy"


@dataclass(frozen=True)
class Instance:
    """Everything the agent is allowed to see."""

    instance_id: str
    seed: int
    chart_of_accounts: tuple[Account, ...]
    # code -> signed natural balance AFTER period GL activity, BEFORE adjustments.
    opening_trial_balance: dict[str, Cents]
    general_ledger: tuple[JournalEntry, ...]
    statements: tuple[Statement, ...]
    policy: PolicySheet

    def account(self, code: str) -> Account:
        for a in self.chart_of_accounts:
            if a.code == code:
                return a
        raise KeyError(code)


class DiscrepancyKind(Enum):
    UNRECORDED_BANK_FEE = "unrecorded_bank_fee"
    TIMING_DIFFERENCE_NOADJUST = "timing_difference_noadjust"
    TRANSPOSITION_ERROR = "transposition_error"
    MISCLASSIFICATION = "misclassification"
    DUPLICATE_ENTRY = "duplicate_entry"
    MISSING_ACCRUAL = "missing_accrual"


@dataclass(frozen=True)
class SeededDiscrepancy:
    disc_id: str
    kind: DiscrepancyKind
    requires_adjustment: bool
    affected_accounts: tuple[str, ...]
    gold_entry: "JournalEntry | None"  # canonical fix; None for the timing trap
    detection_hint: str


@dataclass(frozen=True)
class GroundTruth:
    """The hidden answer key. Never shown to the agent."""

    gold_adjustments: tuple[JournalEntry, ...]
    gold_final_balances: dict[str, Cents]   # authoritative post-close balances
    discrepancies: tuple[SeededDiscrepancy, ...]
    protected_accounts: frozenset[str]
    reconcilable_accounts: frozenset[str]
    timing_trap_amount: "Cents | None" = None  # deposit-in-transit amount (unique per instance)
