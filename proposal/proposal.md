# A Month-End Reconciliation / Close Benchmark for LLM Agents

**One-line thesis.** Reconciliation and close are the finance workflow where you
can build an *objective* agent benchmark — because accounting's consistency laws
(debits = credits, the balance sheet balances, the ledger ties to the statement)
make "the right answer" **computable**, not a matter of opinion. This proposal
designs that benchmark, and ships a runnable reference implementation
(`../src/finbalance/`) that proves the ground truth and verifier are real, not
hand-wavy.

> **Why this capability.** Of the assignment's suggested picks (financial
> modeling, filings analysis, reconciliation, audit checks, IC-memo writing),
> reconciliation/close is the one with (a) the cleanest objective verifier, (b) a
> genuinely long-horizon, tool-using shape (many dependent steps where errors
> compound), and (c) the thinnest prior art. The others lean on fuzzy,
> assumption-dependent, or LLM-judged answers.

---

## 1. The task

The agent plays a staff accountant closing the books for one company-month.

**Given (public inputs):** an opening trial balance (prior period's ending
balances), the general ledger for the month, external statements to reconcile
against (bank, credit-card, AR/AP subledgers), a chart of accounts, and a policy
sheet (accrual rules, materiality, protected accounts).

**Must produce (artifacts):**
1. **Reconciliations** — for each externally-backed account, a schedule bridging
   book balance to statement balance with itemized reconciling items.
2. **Adjusting journal entries (AJEs)** — the corrections, each balanced
   (debits = credits), with account, amount, rationale.
3. A **final adjusted trial balance** and the **financial statements** derived
   from it.

**It is tool-using, not one-shot.** The agent cannot see the whole instance in
one prompt; it acts through a tool API — `query_ledger`, `read_document`,
`get_trial_balance`, `post_journal_entry` (rejected if unbalanced),
`submit_reconciliation` — and the sequence of calls is recorded as a trace. This
is what makes it an *agent* benchmark rather than a QA dataset.

**Every error leaves discoverable evidence.** The generator builds two worlds —
the correct books and the as-booked books — and the difference *is* the error, so
each discrepancy is visible in the documents the agent reads: the duplicate entry
literally appears twice in the ledger, the transposed amount is contradicted by
the bank statement, the unrecorded fee is on the statement but not the books, the
missing accrual has a post-close invoice. An agent can *solve* an instance from
evidence, not just be graded on it (verified across 100+ seeds by the solvability
audit in `tests/test_solvability.py`).

**It is long-horizon.** Difficulty scales on two axes: **breadth** (more
interacting accounts — fixing AP moves cash) and **depth** (sequential months,
where a missed accrual in month 1 silently corrupts month 2 — the compounding
degradation observed in AccountingBench).

**The heart of the task is a seeded discrepancy taxonomy** — real close problems
with known corrections: unrecorded bank fee, **timing difference that must NOT be
adjusted (a deliberate trap)**, transposition/amount error, misclassification,
duplicate entry, missing accrual. Reporting *which kinds* an agent catches vs.
misses is far richer than one aggregate number.

## 2. Ground truth & data

**Decision: a procedural synthetic generator + deterministic ledger replay.** We
generate the books ourselves, so every correct answer — each adjusting entry and
the final balance sheet — is *computed, not hand-labeled*.

**Why synthetic is the only defensible option here (not a compromise).** I
verified via a dedicated research pass that the raw materials reconciliation needs
— a real general ledger *paired with* the external statement it ties to, plus
labeled reconciling items — **are not publicly available.** Everything public is
either *one-sided* (a ledger, or a statement, never the matched pair) or
*synthetic*. The one real matched dataset, AccountingBench (Penrose, real
Ramp/Stripe/Mercury data), was kept **private** — for the structural reason that a
real bank statement tied to a company's ledger is PII- and audit-confidential and
nobody open-sources it. So real data is off the table by construction, and
synthetic generation is the *only* way to get matched inputs with trustworthy
labels.

**Ground truth by construction (see `generator.py`).** Each book error is defined
entirely by its gold adjusting entry; the generator computes that entry's effect
`E` on balances and sets the public opening trial balance to `clean − E`. Applying
the gold entry therefore restores the clean balances *by construction*, and the
generator asserts this at generation time (`replay(opening, gold) == clean` and
both trial balances net to zero). A broken discrepancy can never ship. This is
proven across 200 seeds in `tests/test_generator.py`.

**Contamination resistance.** We release the *generator*, not a fixed test file.
Every instance is a fresh seed, so a model cannot have trained on it — the same
anti-contamination strategy FinBalance and LOGIGEN adopt. Same seed →
byte-identical instance (reproducible); new seed → unseen books.

## 3. Rubric / verifier

**The core score is fully programmatic — no LLM judge** (see `verifier.py`).
Correctness is judged on the *balances that result from replaying the agent's
entries*, never on matching its specific entry text — so any set of entries that
lands the gold balances passes, and alternative-but-correct codings are accepted
for free.

**What is checked programmatically:**

| Metric | Meaning |
|---|---|
| `BSrecon` | Replay the agent's entries from the opening TB; do **all** accounts match gold within $0.01? *(honest headline)* |
| `BSexact` | Does the agent's **self-reported** balance sheet match gold? *(catches narrative ≠ entries)* |
| `accounts_reconciled` | Fraction of reconcilable accounts matching gold *(partial credit)* |
| `discrepancies_caught` | Fraction of book-error discrepancies whose affected accounts match gold *(partial credit, per error type)* |
| `timing_trap_respected` | Did the agent **abstain** from booking any entry that moves cash by the deposit-in-transit amount? (Detected independently: the DIT amount is unique per instance, so the check is not entangled with the other cash fixes.) |
| `caught_by_kind` | Per-error-type diagnostic (effect-matched, so one uncaught error doesn't poison another that shares an account like Operating Expenses). |

**Hard gates → score 0** (borrowed from AppWorld's allowed/forbidden-delta model
and CFAgentBench's money-movement gates):
- `forbidden_touch` — a **protected** account (equity) changed.
- `unauthorized_change` — an account with no legitimate reason to change
  (`gold == opening`) was moved anyway.

**What needs a judge or human (and is kept OUT of the score):** the prose *close
memo* explaining the adjustments. If scored at all, an LLM judge rates narrative
quality **only**, and is **never** used as reward — matching the CFAgentBench
discipline. The number you report never depends on a judge.

**Money is integer cents everywhere**; the "$0.01 tolerance" is literally
`tol_cents = 1`, eliminating floating-point ambiguity.

## 4. Scoring & reporting

**Aggregate:** `raw = 0.6·BSrecon + 0.25·discrepancies_caught +
0.15·accounts_reconciled`, then gates zero it on any unauthorized/forbidden
movement. Trace-level **efficiency** and **tool-call count** are reported
alongside (an agent that reconciles in 4 calls beats one that flails for 40).

**What a score tells you.** BSrecon is pass/fail *closed the books correctly*.
The partial-credit metrics localize *how far* a failing agent got, and the
per-discrepancy breakdown says *which error types* it's blind to. The gates
separate "made a mistake" from "did something dangerous."

**Reliability, not just accuracy.** Following τ-bench, the headline for a
compliance-sensitive workflow should be **pass^k** — the probability the agent
closes correctly on *all* k independent runs — because a close you can only trust
half the time is untrustworthy. (τ-bench found agents at ~50% pass^1 drop below
25% at pass^8.) The `suite` command reports pass^1 for capability and pass^k for
reliability; for a deterministic agent they coincide, and the gap opens exactly
for a stochastic LLM agent, which is where reliability matters.

**The metric has demonstrated resolution.** Four reference agents (run by
`finbalance demo`) calibrate it — and these are *measured*, not hypothetical:

| Agent | Final | What it shows |
|---|---|---|
| Oracle | **1.00** | ceiling; posts the gold adjustments |
| Baseline (tools only) | **0.35** | honest reconciler; catches 4/5 error types, blind to policy accruals |
| Sloppy | **0.00** | raw ≈ 0.04 but **gated** for moving an untouched account — shows why gates exist |
| Null | **0.07** | floor |

**Failure modes the benchmark surfaces (observed):**
- **Blind spots by error type** — the Baseline's `caught_by_kind` pinpoints
  exactly which discrepancy class it misses (accruals), not just an aggregate.
- **The timing-difference trap** — over-eager agents "fix" a deposit in transit
  that needed no entry; detected independently of the other cash adjustments.
- **Unsafe money movement** — the Sloppy agent's gate-to-zero, despite a
  plausible-looking raw score.
- **Long-horizon compounding** — in a `campaign`, the Baseline closes cleanly
  (1.00 → 1.00) until an accrual appears, then **drifts and never recovers**
  (→ 0.34 → 0.34): an uncaught error corrupts every later month's opening, exactly
  the degradation real closes exhibit. The Oracle holds 1.00 throughout.
- **Aggregation gap** (`BSrecon` passes but `BSexact` fails) — correct entries,
  wrong self-reported statement; FinBalance reports 26–41pp gaps here.

## 5. Prior art

The field splits into three tiers; ours sits in the thin, high-value third.

| Benchmark | Capability | Tool-using | Verifier | Ground truth | Public |
|---|---|---|---|---|---|
| FinanceBench / FinQA / TAT-QA / ConvFinQA / BizBench / DocFinQA | Static financial QA | ❌ | exact-match / judge | filings, hand QA | ✅ |
| FinToolBench / FAB / FinAgentBench / BigFinanceBench | Finance **research** agents | ✅ | expert answer + judge | expert-written | mixed |
| **FinBalance** | Multi-doc reconciliation | tool-*light* (one-shot) | **deterministic ledger replay** | synthetic generator | generator claimed, repo unconfirmed |
| AccountingBench | Real month-end close | ✅ | financial-statement accuracy | **private** real data | ❌ |
| EnterpriseArena | 132-mo CFO sim | ✅ (tool budget) | programmatic state score | deterministic sim | preprint |
| CFAgentBench | Construction-finance | ✅ | layered state-diff + gates | seeded env | preprint |
| τ-bench / AppWorld | Tool-agent (retail/apps) | ✅ | final-state vs goal; pass^k | annotated goals | ✅ |
| Finch / LH-Bench | Spreadsheet / enterprise | ✅ | **LLM judge** *(contrast)* | fixed / rubric | ✅ / preprint |

**What existing work measures and where it falls short.** Tier 1 tests reasoning,
not workflow (no tools, no long horizon). Tier 2 makes it agentic but grades
*research* questions with fuzzy expert answers and an LLM judge — the weak link.
The accounting tier has the right idea (objective, replay-based ground truth) but:
FinBalance is essentially **one-shot** (no interactive tool harness) and its public
generator is unconfirmed; AccountingBench's data is **private**; EnterpriseArena
and CFAgentBench are **adjacent domains** (CFO simulation, construction finance).

**What ours adds.** It is the combination none of them offer together:
*general reconciliation/close* scope + an *interactive long-horizon tool-using
harness* + a *procedural contamination-resistant generator* + a *deterministic
ledger-replay verifier with allowed/forbidden-delta gates* + *partial-credit and
trace-level scoring* + *pass^k reliability*. It borrows the best proven ideas —
`BSexact`/`BSrecon` (FinBalance), gold-state-as-balance-vector + collateral-damage
guards (AppWorld), layered gates (CFAgentBench), pass^k (τ-bench) — and unifies
them for the close.

## 6. Scope — what we're NOT measuring, and why

- **Not full GAAP/IFRS judgment.** We fix the policy and chart of accounts so each
  discrepancy has one correct treatment. Materiality judgment, revenue-recognition
  gray areas, and tax provisions are out — they require professional judgment that
  can't be objectively verified, which is the whole reason we scoped to
  reconciliation.
- **Not document/OCR robustness.** Statements are structured, not scanned PDFs.
  Real bundles have messy layouts; that's a separable perception axis.
- **Not real-company data.** By necessity (Section 2) — and the contamination and
  privacy arguments make synthetic *better* here, not worse.
- **Not narrative quality as a score.** The close memo is optional and, if judged,
  never enters the reward.
- **Reference-impl simplifications** (single company, ~14 accounts, one gold
  vector per instance) are documented in the README; the design scales on breadth
  and a `set`-of-gold-vectors seam already exposed in the verifier. Long-horizon
  compounding and multi-agent calibration are *implemented* (`campaign`, `suite`),
  not just designed.

**In one sentence:** we measure whether an agent can *mechanically and reliably
close a set of books correctly and safely* — deliberately excluding subjective
professional judgment, because excluding it is exactly what buys us an objective,
trustworthy score.

---

*The claims in Sections 1–4 are executable. `finbalance demo` runs the generator,
harness, and verifier end-to-end with four calibration agents; `finbalance suite`
reports pass^k and per-type catch rates; `finbalance campaign` shows long-horizon
compounding. `pytest` (31 tests) proves the oracle scores 1.0, the generator's
ground truth is self-consistent, and every seeded error is discoverable from the
documents — across 100+ seeds.*
