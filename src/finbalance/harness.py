"""Agent harness: the tool interface an agent acts through, plus trace recording.

This is the piece that makes the benchmark *tool-using and long-horizon* rather
than a one-shot prompt. The agent never sees the raw instance dict; it must call
tools to read the ledger and documents, post adjusting entries (which are
validated and rejected if unbalanced — the agent can recover and retry), and
finally submit. Every call is recorded in ``trace`` for efficiency scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ledger import Ledger, UnbalancedEntryError, UnknownAccountError
from .model import Instance, JournalEntry
from .money import Cents
from .verifier import Submission


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    ok: bool


@dataclass(frozen=True)
class PostResult:
    ok: bool
    entry_id: "str | None"
    reason: "str | None"


class AgentSession:
    def __init__(self, instance: Instance):
        self._instance = instance
        self._work = Ledger(instance.chart_of_accounts, instance.opening_trial_balance)
        self._agent_entries: list[JournalEntry] = []
        self.trace: list[ToolCall] = []

    # -- read tools ----------------------------------------------------------
    def query_ledger(self, account: "str | None" = None) -> list[dict]:
        """Return posted general-ledger entries, optionally filtered by account."""
        rows = []
        for e in self._instance.general_ledger:
            if account is None or any(l.account == account for l in e.lines):
                rows.append(
                    {"entry_id": e.entry_id, "date": e.date, "memo": e.memo,
                     "lines": [(l.account, l.debit, l.credit) for l in e.lines]}
                )
        self.trace.append(ToolCall("query_ledger", {"account": account}, True))
        return rows

    def list_documents(self) -> list[str]:
        docs = [s.doc_id for s in self._instance.statements] + [self._instance.policy.doc_id]
        self.trace.append(ToolCall("list_documents", {}, True))
        return docs

    def read_document(self, doc_id: str) -> dict:
        """Read a statement or the policy sheet by doc id."""
        for s in self._instance.statements:
            if s.doc_id == doc_id:
                self.trace.append(ToolCall("read_document", {"doc_id": doc_id}, True))
                return {
                    "kind": s.kind, "account_code": s.account_code,
                    "opening_balance": s.opening_balance, "closing_balance": s.closing_balance,
                    "lines": [(l.line_id, l.date, l.description, l.amount, l.ext_ref) for l in s.lines],
                }
        if doc_id == self._instance.policy.doc_id:
            p = self._instance.policy
            self.trace.append(ToolCall("read_document", {"doc_id": doc_id}, True))
            return {"period_end": p.period_end, "materiality_cents": p.materiality_cents,
                    "accrual_rules": list(p.accrual_rules), "protected_accounts": list(p.protected_accounts)}
        self.trace.append(ToolCall("read_document", {"doc_id": doc_id}, False))
        raise KeyError(doc_id)

    def get_trial_balance(self) -> dict[str, Cents]:
        """Current working balances (opening + any entries the agent has posted)."""
        self.trace.append(ToolCall("get_trial_balance", {}, True))
        return self._work.balances()

    # -- write tool (validated; returns rejection rather than raising) --------
    def post_journal_entry(self, entry: JournalEntry) -> PostResult:
        try:
            self._work.post(entry)
        except (UnbalancedEntryError, UnknownAccountError) as exc:
            self.trace.append(ToolCall("post_journal_entry", {"entry_id": entry.entry_id}, False))
            return PostResult(ok=False, entry_id=entry.entry_id, reason=str(exc))
        self._agent_entries.append(entry)
        self.trace.append(ToolCall("post_journal_entry", {"entry_id": entry.entry_id}, True))
        return PostResult(ok=True, entry_id=entry.entry_id, reason=None)

    # -- terminal ------------------------------------------------------------
    def submit_reconciliation(self, reported_balance_sheet: dict[str, Cents]) -> Submission:
        return Submission(
            entries=tuple(self._agent_entries),
            reported_bs=dict(reported_balance_sheet),
            trace=tuple(self.trace),
        )
