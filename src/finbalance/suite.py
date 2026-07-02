"""Suite runner: evaluate an agent over many instances and report aggregates.

Reports the metrics that matter for a compliance-sensitive workflow:

* **pass^1** — probability a single run closes the books correctly (BSrecon).
* **pass^k** — probability *all* k independent runs of the same instance succeed
  (τ-bench's reliability metric). For a deterministic agent pass^k == pass^1; the
  gap only opens for a stochastic agent (e.g. an LLM at temperature > 0), which is
  exactly where reliability matters.
* **per-discrepancy catch rates** — which error types the agent is blind to.
* **gate triggers** — how often the agent did something unsafe.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .agents import AGENTS
from .generator import generate_instance
from .harness import AgentSession
from .verifier import score


@dataclass
class SuiteResult:
    agent: str
    n_seeds: int
    runs: int
    k: int
    pass_1: float
    pass_k: float
    mean_final: float
    trap_respected_rate: float
    forbidden_rate: float
    unauthorized_rate: float
    catch_rate_by_kind: dict
    mean_tool_calls: float


def run_suite(agent_name: str, seeds: range, runs: int = 1, k: int = 5) -> SuiteResult:
    agent_factory = AGENTS[agent_name]
    per_seed_all_pass = []
    single_run_passes = 0
    total_runs = 0
    finals = []
    trap = 0
    gates = {"forbidden": 0, "unauthorized": 0}
    tool_calls = 0
    kind_hit: dict = defaultdict(int)
    kind_tot: dict = defaultdict(int)

    for seed in seeds:
        run_passes = []
        for _ in range(runs):
            inst, gt = generate_instance(seed, k=k)
            sc = score(inst, gt, agent_factory().run(AgentSession(inst), gt))
            finals.append(sc.final_score)
            run_passes.append(sc.bs_recon)
            single_run_passes += 1 if sc.bs_recon else 0
            trap += 1 if sc.timing_trap_respected else 0
            gates["forbidden"] += 1 if sc.forbidden_touch else 0
            gates["unauthorized"] += 1 if sc.unauthorized_change else 0
            tool_calls += sc.tool_calls
            for kind, hit in (sc.caught_by_kind or {}).items():
                kind_tot[kind] += 1
                kind_hit[kind] += 1 if hit else 0
            total_runs += 1
        per_seed_all_pass.append(all(run_passes))

    n = len(per_seed_all_pass)
    return SuiteResult(
        agent=agent_name, n_seeds=n, runs=runs, k=k,
        pass_1=single_run_passes / total_runs,
        pass_k=sum(per_seed_all_pass) / n,
        mean_final=sum(finals) / len(finals),
        trap_respected_rate=trap / total_runs,
        forbidden_rate=gates["forbidden"] / total_runs,
        unauthorized_rate=gates["unauthorized"] / total_runs,
        catch_rate_by_kind={k2: kind_hit[k2] / kind_tot[k2] for k2 in sorted(kind_tot)},
        mean_tool_calls=tool_calls / total_runs,
    )


def format_suite(res: SuiteResult) -> str:
    lines = [
        f"Suite: agent={res.agent}  seeds={res.n_seeds}  runs/seed={res.runs}  k(book-errors)={res.k}",
        "-" * 52,
        f"  pass^1 (single-run BSrecon) : {res.pass_1:.2%}",
    ]
    if res.runs > 1:
        lines.append(f"  pass^{res.runs} (all {res.runs} runs pass)   : {res.pass_k:.2%}")
    lines += [
        f"  mean final score            : {res.mean_final:.3f}",
        f"  timing trap respected       : {res.trap_respected_rate:.2%}",
        f"  gate: unauthorized_change   : {res.unauthorized_rate:.2%}",
        f"  gate: forbidden_touch       : {res.forbidden_rate:.2%}",
        f"  mean tool calls             : {res.mean_tool_calls:.1f}",
        "  catch rate by discrepancy kind:",
    ]
    for kind, rate in res.catch_rate_by_kind.items():
        lines.append(f"      {kind:<24} {rate:.2%}")
    return "\n".join(lines)
