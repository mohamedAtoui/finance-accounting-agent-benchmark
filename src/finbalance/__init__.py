"""finbalance — a month-end reconciliation / close agent benchmark.

A procedural synthetic generator produces a fresh "company-month" (opening trial
balance, general ledger, external statements) with a controlled set of seeded
discrepancies whose correct fixes are known by construction. A deterministic
double-entry ledger-replay verifier scores an agent's adjusting journal entries
against that computable ground truth — no LLM judge in the core score.

See ``proposal/proposal.md`` for the design writeup and ``README.md`` for a
one-command quickstart.
"""

__version__ = "0.1.0"
