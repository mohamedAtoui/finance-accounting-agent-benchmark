"""Double-entry ledger engine and deterministic replay.

The ledger tracks each account's balance as a signed integer in "natural units":
a debit-normal account increases with debits, a credit-normal account increases
with credits. A journal line carries a ``debit`` and a ``credit`` amount (exactly
one nonzero by convention). Posting applies ``delta = debit - credit`` to a
debit-normal account, and its negation to a credit-normal account. This makes the
whole trial-balance check a single sum over accounts.

:func:`replay` is the heart of the verifier: it takes an agent's adjusting
entries, applies them to the *opening* trial balance (which already reflects the
period GL activity), and reports the resulting balances plus which entries were
rejected and which accounts were touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import Account, JournalEntry, Side
from .money import Cents


class UnbalancedEntryError(ValueError):
    pass


class UnknownAccountError(ValueError):
    pass


class Ledger:
    def __init__(self, coa: Iterable[Account], opening: dict[str, Cents]):
        self._accts: dict[str, Account] = {a.code: a for a in coa}
        # Start from a copy so callers' dicts aren't mutated. Unknown opening
        # codes are a programming error in the generator, so surface them.
        self._bal: dict[str, Cents] = {}
        for code in self._accts:
            self._bal[code] = opening.get(code, 0)
        for code in opening:
            if code not in self._accts:
                raise UnknownAccountError(f"opening balance for unknown account {code!r}")

    def post(self, entry: JournalEntry) -> None:
        if not entry.is_balanced():
            raise UnbalancedEntryError(
                f"entry {entry.entry_id!r}: debits {entry.total_debit()} "
                f"!= credits {entry.total_credit()}"
            )
        for line in entry.lines:
            acct = self._accts.get(line.account)
            if acct is None:
                raise UnknownAccountError(f"entry {entry.entry_id!r}: unknown account {line.account!r}")
            signed = line.debit - line.credit  # positive == net debit
            if acct.normal_side is Side.DEBIT:
                self._bal[line.account] += signed
            else:
                self._bal[line.account] -= signed

    def balances(self) -> dict[str, Cents]:
        return dict(self._bal)

    def balance(self, code: str) -> Cents:
        return self._bal[code]

    def trial_balance_check(self) -> Cents:
        """Total debits minus total credits across all accounts; 0 == balanced.

        Converts each signed natural balance back into raw debit/credit terms and
        sums. A correct set of books always returns 0.
        """
        total = 0
        for code, natural in self._bal.items():
            acct = self._accts[code]
            # Raw debit-minus-credit for this account:
            raw = natural if acct.normal_side is Side.DEBIT else -natural
            total += raw
        return total


@dataclass(frozen=True)
class ReplayResult:
    final: dict[str, Cents]
    rejected: tuple[tuple[str, str], ...]  # (entry_id, reason)
    touched: frozenset[str]                # accounts named in accepted entries


def replay(
    coa: Iterable[Account],
    opening_balances: dict[str, Cents],
    agent_entries: Iterable[JournalEntry],
) -> ReplayResult:
    """Apply agent entries to the opening trial balance deterministically.

    Rejected entries (unbalanced or referencing unknown accounts) are collected
    rather than raised, mirroring how the harness rejects a bad post — a robust
    verifier must never crash on a malformed agent submission.
    """
    coa = tuple(coa)
    led = Ledger(coa, opening_balances)
    rejected: list[tuple[str, str]] = []
    touched: set[str] = set()
    for entry in agent_entries:
        try:
            led.post(entry)
        except (UnbalancedEntryError, UnknownAccountError) as exc:
            rejected.append((entry.entry_id, str(exc)))
            continue
        touched.update(line.account for line in entry.lines)
    return ReplayResult(final=led.balances(), rejected=tuple(rejected), touched=frozenset(touched))
