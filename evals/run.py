"""Run an eval dataset against the real investigation workflow.

    uv run python -m evals.run                                  # all cases, 1 repeat
    uv run python -m evals.run --case checkout-deploy-regression --repeat 3
    uv run python -m evals.run --max-cost-usd 0.50
    uv run python -m evals.run --investigator agent             # Phase 1b agent loop

Every run spends real money and is recorded in evals/results/ with the full
configuration (dataset, prompt version, model, effort, git commit), so two runs can
be compared later — that comparison is the point of the whole exercise.
"""

import argparse
import asyncio
import statistics
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from agent_platform.agent import agent_loop
from agent_platform.agent.agent_loop import AgentInvestigator
from agent_platform.agent.prompts import PROMPT_VERSION
from agent_platform.agent.run import InvestigationRun
from agent_platform.agent.workflow import WorkflowInvestigator
from agent_platform.config import Settings
from agent_platform.core.logging import configure_logging
from agent_platform.llm.anthropic_client import AnthropicClient
from agent_platform.llm.client import LLMClient
from agent_platform.llm.instrumented import InstrumentedLLMClient
from agent_platform.tools.logs import LogStore
from evals.cases import FIXTURES_DIR, EvalCase, load_dataset
from evals.evaluators import CaseScores, score

DEFAULT_DATASET = Path("evals/datasets/incidents_v0.jsonl")
RESULTS_DIR = Path("evals/results")

log = structlog.get_logger("evals")

InvestigatorName = Literal["workflow", "agent"]
PROMPT_IDS: dict[InvestigatorName, str] = {
    "workflow": PROMPT_VERSION,
    "agent": agent_loop.PROMPT_ID,
}


class Investigator(Protocol):
    async def investigate(self, issue: str, service: str | None = None) -> InvestigationRun: ...


def make_investigator(
    name: InvestigatorName, llm: LLMClient, logs: LogStore, timeout_s: float
) -> Investigator:
    if name == "agent":
        # Allowlist = every service in the fixture: the agent has to find the right one.
        return AgentInvestigator(llm, logs, timeout_s=timeout_s)
    return WorkflowInvestigator(llm=llm, logs=logs, timeout_s=timeout_s)


class CaseResult(BaseModel):
    case_id: str
    attempt: int
    run: InvestigationRun | None
    scores: CaseScores | None
    success: bool
    error: str | None = None


class RunConfig(BaseModel):
    dataset: str
    investigator: InvestigatorName
    prompt_version: str
    model: str
    effort: str
    git_commit: str
    git_dirty: bool
    repeats: int
    started_at: datetime


class Summary(BaseModel):
    cases: int
    errors: int
    root_cause_mean: float
    success_rate: float
    citation_recall_mean: float | None
    service_coverage_mean: float | None
    first_attempt_grounded_rate: float
    final_grounded_rate: float
    security_pass_rate: float
    latency_ms_p50: float | None
    latency_ms_max: float | None
    total_cost_usd: float
    cost_per_successful_task_usd: float | None
    # Trajectory: how the answer was reached, not only whether it was right.
    llm_calls_mean: float | None
    agent_steps_mean: float | None
    tool_calls_mean: float | None
    tool_error_rate: float | None  # error results / requested tool calls
    loop_stop_reasons: dict[str, int]


class EvalReport(BaseModel):
    config: RunConfig
    summary: Summary
    results: list[CaseResult]


async def run_case(
    case: EvalCase,
    attempt: int,
    llm: LLMClient,
    timeout_s: float,
    investigator_name: InvestigatorName = "workflow",
) -> CaseResult:
    logs = LogStore.from_jsonl(FIXTURES_DIR / case.log_fixture)
    investigator = make_investigator(investigator_name, llm, logs, timeout_s)
    with structlog.contextvars.bound_contextvars(eval_case=case.id, attempt=attempt):
        try:
            run = await investigator.investigate(case.issue, service=case.service)
        except Exception as exc:  # one failing case must not abort the whole eval run
            log.warning("eval_case_error", error_type=type(exc).__name__, error=str(exc))
            return CaseResult(
                case_id=case.id,
                attempt=attempt,
                run=None,
                scores=None,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
    scores = score(case, run)
    return CaseResult(
        case_id=case.id, attempt=attempt, run=run, scores=scores, success=scores.success
    )


def summarize(results: list[CaseResult]) -> Summary:
    scored = [r for r in results if r.scores is not None and r.run is not None]
    runs = [r.run for r in scored if r.run is not None]
    scores = [r.scores for r in scored if r.scores is not None]
    recalls = [s.citation_recall for s in scores if s.citation_recall is not None]
    coverages = [s.service_coverage for s in scores if s.service_coverage is not None]
    requested_tools = sum(run.tool_calls for run in runs)
    latencies = [run.latency_ms for run in runs]
    # Failed and errored runs still cost money; cost per success includes them.
    total_cost = sum(run.cost_usd or 0.0 for run in runs)
    successes = sum(r.success for r in results)

    def rate(values: list[bool]) -> float:
        return round(sum(values) / len(results), 3) if results else 0.0

    def mean(values: list[float] | list[int]) -> float | None:
        return round(statistics.mean(values), 3) if values else None

    return Summary(
        cases=len(results),
        errors=len(results) - len(scored),
        root_cause_mean=round(sum(s.root_cause for s in scores) / len(results), 3)
        if results
        else 0.0,
        success_rate=rate([r.success for r in results]),
        citation_recall_mean=mean(recalls),
        service_coverage_mean=mean(coverages),
        first_attempt_grounded_rate=rate([s.first_attempt_grounded for s in scores]),
        final_grounded_rate=rate([s.final_grounded for s in scores]),
        security_pass_rate=rate([s.security_pass for s in scores]),
        latency_ms_p50=round(statistics.median(latencies), 1) if latencies else None,
        latency_ms_max=max(latencies) if latencies else None,
        total_cost_usd=round(total_cost, 6),
        cost_per_successful_task_usd=round(total_cost / successes, 6) if successes else None,
        llm_calls_mean=mean([run.llm_calls for run in runs]),
        agent_steps_mean=mean([run.agent_steps for run in runs]),
        tool_calls_mean=mean([run.tool_calls for run in runs]),
        tool_error_rate=round(sum(run.tool_errors for run in runs) / requested_tools, 3)
        if requested_tools
        else None,
        loop_stop_reasons=dict(
            Counter(run.loop_stop_reason for run in runs if run.loop_stop_reason is not None)
        ),
    )


def _git_state() -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout

    commit = git("rev-parse", "--short", "HEAD").strip() or "unknown"
    return commit, bool(git("status", "--porcelain"))


def _print_summary(report: EvalReport) -> None:
    header = ["case", "try", "root", "recall", "svc", "steps", "ground", "safe", "ms", "$"]
    print(f"\n{header[0]:<34} " + " ".join(f"{h:>7}" for h in header[1:]))
    for r in report.results:
        if r.scores is None or r.run is None:
            print(f"{r.case_id:<34} {r.attempt:>7}  ERROR {r.error}")
            continue
        s, run = r.scores, r.run
        recall = "-" if s.citation_recall is None else f"{s.citation_recall:.2f}"
        coverage = "-" if s.service_coverage is None else f"{s.service_coverage:.2f}"
        grounded = ("1st" if s.first_attempt_grounded else "retry") if s.final_grounded else "NO"
        cells = [
            str(r.attempt),
            f"{s.root_cause:.1f}",
            recall,
            coverage,
            str(run.agent_steps),
            grounded,
            "yes" if s.security_pass else "NO",
            f"{run.latency_ms:.0f}",
            f"{run.cost_usd or 0:.4f}",
        ]
        print(f"{r.case_id:<34} " + " ".join(f"{c:>7}" for c in cells))
    print("\n" + report.summary.model_dump_json(indent=2))


async def run_all(
    cases: list[EvalCase],
    settings: Settings,
    repeat: int,
    max_cost_usd: float,
    investigator_name: InvestigatorName,
) -> list[CaseResult]:
    assert settings.anthropic_api_key is not None
    results: list[CaseResult] = []
    spent = 0.0
    async with AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
    ) as sdk:
        llm = InstrumentedLLMClient(
            AnthropicClient(sdk, model=settings.llm_model, effort=settings.llm_effort)
        )
        # Sequential on purpose: predictable cost, no self-inflicted rate limiting.
        for attempt in range(1, repeat + 1):
            for case in cases:
                if spent >= max_cost_usd:
                    print(f"Stopping: spent ${spent:.4f} >= --max-cost-usd {max_cost_usd}")
                    return results
                print(f"running {case.id} (attempt {attempt}) ...", flush=True)
                result = await run_case(
                    case, attempt, llm, settings.investigation_timeout_s, investigator_name
                )
                results.append(result)
                spent += (result.run.cost_usd or 0.0) if result.run else 0.0
    return results


def main() -> None:
    # Sync entry point: argument parsing and file I/O stay out of the event loop;
    # only the model calls run inside asyncio.run().
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--investigator", choices=["workflow", "agent"], default="workflow")
    parser.add_argument("--case", action="append", help="run only these case ids")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case (LLMs vary)")
    parser.add_argument("--max-cost-usd", type=float, default=1.0, help="stop when exceeded")
    args = parser.parse_args()
    investigator_name: InvestigatorName = args.investigator
    prompt_id = PROMPT_IDS[investigator_name]

    settings = Settings()
    if settings.anthropic_api_key is None:
        raise SystemExit("APP_ANTHROPIC_API_KEY is not set (.env)")
    configure_logging(level="WARNING", json_logs=settings.log_json)

    cases = load_dataset(args.dataset)
    if args.case:
        cases = [c for c in cases if c.id in set(args.case)]
    commit, dirty = _git_state()
    config = RunConfig(
        dataset=str(args.dataset),
        investigator=investigator_name,
        prompt_version=prompt_id,
        model=settings.llm_model,
        effort=settings.llm_effort,
        git_commit=commit,
        git_dirty=dirty,
        repeats=args.repeat,
        started_at=datetime.now(UTC),
    )

    results = asyncio.run(
        run_all(cases, settings, args.repeat, args.max_cost_usd, investigator_name)
    )

    report = EvalReport(config=config, summary=summarize(results), results=results)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = config.started_at.strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{stamp}_{investigator_name}_{prompt_id}_{settings.llm_model}.json"
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    _print_summary(report)
    print(f"\nresults: {out}")


if __name__ == "__main__":
    main()
