# Live-discussion notes (prep sheet — not part of the proposal)

## The opening line

> "You build RL environments, so I optimized for **reward-signal quality** above
> everything else: a verifier that is fully programmatic, ungameable, cheap at
> scale, and impossible to contaminate. Reconciliation is the one finance
> workflow where all four are achievable at once."

## Why not the other four capabilities (researched, with the fatal detail)

| Capability | Fatal detail for an RL-grade benchmark |
|---|---|
| **Financial modeling** | The flagship benchmark (FrontierFinance, arXiv 2604.05912) grades with human experts + hand rubrics, **18+ hours of skilled labor per task**, 25 tasks total. Not programmatic, not scalable — no reward function. |
| **Audit checks (AAER/restatements)** | Real labels exist (free AAER set: 1,816 events; 8-K Item 4.02 filings: ~8k restatements) **but they end pre-training-cutoff and are famous public events** — the model may simply *remember* which companies were caught. Reward could be memorization. Also: no-AAER ≠ clean (undetected fraud → noisy negatives). |
| **Filings analysis** | XBRL tags give a real answer key, but directly-tagged questions collapse to **lookup**, and the space is crowded (FinTagging, FinAuditing, FAB, FinAgentBench). Fifth entrant, weak delta. |
| **IC-memo writing** | No objective right answer; scoring is an LLM judge end to end — the weakest reward signal of all. |
| **Reconciliation (chosen)** | Perfect labels (we plant the errors), contamination-immune (fresh books per seed), fully programmatic verifier (double-entry replay). The one flaw — synthetic inputs — is the *only* flaw you can fully control, and Track B covers external validity. |

## The "public filings are the obvious source" line — answer proactively

- Filings are the **already-reconciled output**, not the reconciliation *input*.
  The inputs (a ledger paired with the bank statement it must tie to, plus
  reconciling items) are PII/audit-confidential — a dedicated research pass found
  no public matched pair; the one real dataset (AccountingBench/Penrose) stayed
  private for exactly that reason.
- Where public filings *do* work objectively, I use them: **Track B tie-outs**
  (reproduce the audited XBRL number from the filing's own sub-schedules).
- Deviating from the "obvious source" with receipts is the point of the
  parenthetical: what matters is "how you decide what the right answer even is,"
  and synthetic construction is the only path to a *provably* right answer here.

## Caveats to own before they're raised

1. **"You spent more than 4 hours."** The proposal is the 4-hour deliverable and
   stands alone. The code exists because a verifier claim you can't run is just a
   claim — I de-risked the design, I'm not padding it.
2. **"Synthetic books are clean/simple."** True and documented (README scope):
   structured statements, ~14 accounts, 6 error types. OCR-mess and GAAP judgment
   are deliberately out of scope — excluding subjective judgment is what buys an
   objective score. The generator's difficulty dials (breadth, depth, subtler
   errors) are the roadmap, not a redesign.
3. **"Could an agent game the verifier?"** Balance-based scoring can't be gamed
   by prose; unbalanced entries are rejected at post time and re-checked at
   replay; plugging differences into unrelated accounts trips the
   `unauthorized_change` gate (SloppyAgent demos this: raw 0.04 → final 0.00).

## Live demo (zero dependencies)

```bash
PYTHONPATH=src python -m finbalance.cli demo --seed 1          # 4-agent scorecard
PYTHONPATH=src python -m finbalance.cli suite --agent baseline --seeds 0:50
PYTHONPATH=src python -m finbalance.cli campaign --agent baseline --seed 1 --months 4
```

Talking points while it runs:
- Spread **1.00 / 0.35 / 0.00 / 0.07** = the metric has resolution, not just a ceiling.
- Baseline uses *only the tools* — it is the executable proof instances are
  solvable from evidence.
- Campaign `1.00 → 1.00 → 0.34 → 0.34` = compounding: one missed accrual corrupts
  every later month's opening. Long-horizon made measurable.

## Likely questions → answers

- **Why not an LLM judge anywhere?** It is allowed — quarantined to the optional
  close-memo narrative, never in the reward (CFAgentBench discipline). Judges
  drift, disagree, and are attackable; a reward function can't be.
- **How does partial credit work?** Per-account reconciled + per-error-type
  caught (effect-matched so one miss doesn't poison a shared account), under a
  balance-based headline (BSrecon). Gates zero everything on unsafe money moves.
- **What's the timing trap for?** Knowing when to do *nothing* — booking a
  deposit-in-transit is the classic tell of pattern-matching over understanding.
  Detected independently via a per-instance-unique amount.
- **How would you train on this (RL)?** Reward = final gated score; dense shaping
  available from per-discrepancy credit; fresh seeds per episode kill reward
  hacking via memorization; pass^k as the eval-time reliability bar.
- **How does it scale in difficulty?** More accounts/statements (breadth), more
  months (depth), subtler/overlapping errors, ambiguity via gold-vector *sets*
  (seam already in the verifier), messy-document rendering as a perception axis.
