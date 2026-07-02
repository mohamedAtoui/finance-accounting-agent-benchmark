"""Stable JSON serialization for instances and ground truth.

Keys are sorted and amounts are integer cents, so the same seed produces
byte-identical files (contamination-resistant + reviewable in git). The public
``instance.json`` never contains ground truth; the answer key lives in a separate
``solution.json`` that a benchmark host would withhold from the agent.
"""

from __future__ import annotations

import json

from .model import (
    Account,
    AcctType,
    DiscrepancyKind,
    GroundTruth,
    Instance,
    JournalEntry,
    JournalLine,
    PolicySheet,
    SeededDiscrepancy,
    Side,
    Statement,
    StatementLine,
)


def _entry_to_dict(e: JournalEntry) -> dict:
    return {"entry_id": e.entry_id, "date": e.date, "memo": e.memo, "source": e.source,
            "lines": [{"account": l.account, "debit": l.debit, "credit": l.credit} for l in e.lines]}


def _entry_from_dict(d: dict) -> JournalEntry:
    lines = tuple(JournalLine(l["account"], l.get("debit", 0), l.get("credit", 0)) for l in d["lines"])
    return JournalEntry(d["entry_id"], d["date"], d["memo"], lines, d.get("source", "GL"))


def instance_to_dict(inst: Instance) -> dict:
    return {
        "instance_id": inst.instance_id,
        "seed": inst.seed,
        "chart_of_accounts": [
            {"code": a.code, "name": a.name, "type": a.type.value, "normal_side": a.normal_side.value,
             "reconcilable": a.reconcilable, "protected": a.protected}
            for a in inst.chart_of_accounts
        ],
        "opening_trial_balance": dict(sorted(inst.opening_trial_balance.items())),
        "general_ledger": [_entry_to_dict(e) for e in inst.general_ledger],
        "statements": [
            {"kind": s.kind, "account_code": s.account_code, "opening_balance": s.opening_balance,
             "closing_balance": s.closing_balance,
             "lines": [{"line_id": l.line_id, "date": l.date, "description": l.description,
                        "amount": l.amount, "ext_ref": l.ext_ref} for l in s.lines]}
            for s in inst.statements
        ],
        "policy": {"period_end": inst.policy.period_end, "materiality_cents": inst.policy.materiality_cents,
                   "accrual_rules": list(inst.policy.accrual_rules),
                   "protected_accounts": list(inst.policy.protected_accounts)},
    }


def instance_from_dict(d: dict) -> Instance:
    coa = tuple(
        Account(a["code"], a["name"], AcctType(a["type"]), Side(a["normal_side"]),
                a["reconcilable"], a["protected"])
        for a in d["chart_of_accounts"]
    )
    statements = tuple(
        Statement(s["kind"], s["account_code"], s["opening_balance"], s["closing_balance"],
                  tuple(StatementLine(l["line_id"], l["date"], l["description"], l["amount"], l["ext_ref"])
                        for l in s["lines"]))
        for s in d["statements"]
    )
    p = d["policy"]
    policy = PolicySheet(p["period_end"], p["materiality_cents"], tuple(p["accrual_rules"]),
                         tuple(p["protected_accounts"]))
    return Instance(
        instance_id=d["instance_id"], seed=d["seed"], chart_of_accounts=coa,
        opening_trial_balance={k: int(v) for k, v in d["opening_trial_balance"].items()},
        general_ledger=tuple(_entry_from_dict(e) for e in d["general_ledger"]),
        statements=statements, policy=policy,
    )


def solution_to_dict(gt: GroundTruth) -> dict:
    return {
        "gold_adjustments": [_entry_to_dict(e) for e in gt.gold_adjustments],
        "gold_final_balances": dict(sorted(gt.gold_final_balances.items())),
        "discrepancies": [
            {"disc_id": d.disc_id, "kind": d.kind.value, "requires_adjustment": d.requires_adjustment,
             "affected_accounts": list(d.affected_accounts),
             "gold_entry": _entry_to_dict(d.gold_entry) if d.gold_entry else None,
             "detection_hint": d.detection_hint}
            for d in gt.discrepancies
        ],
        "protected_accounts": sorted(gt.protected_accounts),
        "reconcilable_accounts": sorted(gt.reconcilable_accounts),
        "timing_trap_amount": gt.timing_trap_amount,
    }


def solution_from_dict(d: dict) -> GroundTruth:
    discs = tuple(
        SeededDiscrepancy(
            x["disc_id"], DiscrepancyKind(x["kind"]), x["requires_adjustment"],
            tuple(x["affected_accounts"]),
            _entry_from_dict(x["gold_entry"]) if x["gold_entry"] else None,
            x["detection_hint"],
        )
        for x in d["discrepancies"]
    )
    return GroundTruth(
        gold_adjustments=tuple(_entry_from_dict(e) for e in d["gold_adjustments"]),
        gold_final_balances={k: int(v) for k, v in d["gold_final_balances"].items()},
        discrepancies=discs,
        protected_accounts=frozenset(d["protected_accounts"]),
        reconcilable_accounts=frozenset(d["reconcilable_accounts"]),
        timing_trap_amount=d.get("timing_trap_amount"),
    )


def dumps(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)
