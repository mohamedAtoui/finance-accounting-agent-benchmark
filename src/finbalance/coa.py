"""Fixed chart of accounts and policy sheet.

The chart is intentionally small (~14 accounts) so a reviewer can hold the whole
close in their head. It is also intentionally *unambiguous*: each seeded
discrepancy type maps to exactly one correct account, so there is a single gold
balance vector per instance (see the note in :mod:`finbalance.verifier`).

Design touches worth noting:
* Protected equity accounts (Common Stock, Retained Earnings) give the
  forbidden-delta guard something real to protect.
* Accumulated Depreciation is a contra-asset carried on the CREDIT side, which
  exercises the signed-balance logic in the ledger.
"""

from __future__ import annotations

from .model import Account, AcctType, PolicySheet, Side

# code, name, type, reconcilable, protected, [normal_side override]
_ROWS: tuple[tuple, ...] = (
    ("1000", "Cash - Operating", AcctType.ASSET, True, False, None),
    ("1100", "Accounts Receivable", AcctType.ASSET, True, False, None),
    ("1200", "Prepaid Expenses", AcctType.ASSET, False, False, None),
    ("1500", "Equipment", AcctType.ASSET, False, False, None),
    ("1510", "Accumulated Depreciation", AcctType.ASSET, False, False, Side.CREDIT),
    ("2000", "Accounts Payable", AcctType.LIABILITY, True, False, None),
    ("2100", "Credit Card Payable", AcctType.LIABILITY, True, False, None),
    ("2200", "Accrued Liabilities", AcctType.LIABILITY, False, False, None),
    ("2300", "Sales Tax Payable", AcctType.LIABILITY, False, False, None),
    ("3000", "Common Stock", AcctType.EQUITY, False, True, None),
    ("3100", "Retained Earnings", AcctType.EQUITY, False, True, None),
    ("4000", "Revenue", AcctType.REVENUE, False, False, None),
    ("5000", "Operating Expenses", AcctType.EXPENSE, False, False, None),
    ("5100", "Bank Fees", AcctType.EXPENSE, False, False, None),
)

# Semantic aliases used by the generator/discrepancies so intent is legible.
CASH = "1000"
AR = "1100"
PREPAID = "1200"
EQUIPMENT = "1500"
ACCUM_DEPR = "1510"
AP = "2000"
CREDIT_CARD = "2100"
ACCRUED_LIAB = "2200"
SALES_TAX = "2300"
COMMON_STOCK = "3000"
RETAINED_EARNINGS = "3100"
REVENUE = "4000"
OP_EXPENSE = "5000"
BANK_FEES = "5100"


def build_chart_of_accounts() -> tuple[Account, ...]:
    from .model import NORMAL_SIDE

    out: list[Account] = []
    for code, name, atype, recon, protected, override in _ROWS:
        side = override if override is not None else NORMAL_SIDE[atype]
        out.append(
            Account(
                code=code,
                name=name,
                type=atype,
                normal_side=side,
                reconcilable=recon,
                protected=protected,
            )
        )
    return tuple(out)


def build_policy(period_end: str) -> PolicySheet:
    return PolicySheet(
        period_end=period_end,
        materiality_cents=500,  # $5.00 — below this, informational only
        accrual_rules=(
            "Accrue known unbilled operating expenses incurred in the period.",
            "Record all bank service charges appearing on the bank statement.",
            "Do not adjust the ledger for timing differences (deposits in "
            "transit, outstanding checks); disclose them as reconciling items.",
        ),
        protected_accounts=(COMMON_STOCK, RETAINED_EARNINGS),
    )
