"""Run the golden set against one agent version and write a report.

    uv run python -m evals.run --version v1                 # every failure mode on
    uv run python -m evals.run --version v2                 # fixed
    uv run python -m evals.run --version v2 --failure-mode date_boundary --cases revenue_last_month

Every run is traced with its eval_case_id, and grouped into one session per eval run.
"""

import argparse
from datetime import UTC, datetime

from evals.cases import GoldenCase, expected_rows, load_cases
from evals.report import write_run_report
from evals.scoring import CaseResult, report_sections, score
from ledgerlens.agent.failure_modes import active_failure_modes, label
from ledgerlens.agent.llm import daily_quota_exhausted
from ledgerlens.core.config import get_settings
from ledgerlens.core.logging import setup_logging
from ledgerlens.core.tracing import setup_tracing, shutdown_tracing
from ledgerlens.db.connection import create_agent_pool
from ledgerlens.schemas.ask import AskRequest
from ledgerlens.schemas.run import RunRecord
from ledgerlens.services.agent_service import AgentRunError, AgentService
from ledgerlens.services.run_store import RunStore
from ledgerlens.sql.catalog import load_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run", description="Run the golden set.")
    parser.add_argument("--version", choices=["v1", "v2"], required=True)
    parser.add_argument("--failure-mode", default="none", help="re-add failure modes to v2")
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--label", help="report name (default: the version)")
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(
        update={"agent_version": args.version, "failure_mode": args.failure_mode}
    )
    failures = label(active_failure_modes(settings.agent_version, settings.failure_mode))
    cases = load_cases(args.cases.split(",") if args.cases else None)
    started = datetime.now(UTC)
    session_id = f"eval-{args.label or args.version}-{started:%Y%m%dT%H%M%S}"
    setup_logging("CRITICAL")  # crashes are recorded in the report
    tracer_provider = setup_tracing(settings)
    store = RunStore(settings.runs_dir)
    results: list[CaseResult] = []
    stopped_early = None
    print(f"{len(cases)} cases · agent {args.version} · failure modes: {failures}")
    try:
        with create_agent_pool(settings) as pool:
            with pool.connection() as conn:
                catalog = load_catalog(conn)
                expected = {case.id: expected_rows(conn, case) for case in cases}
            service = AgentService(settings, pool, store)
            for number, case in enumerate(cases, 1):
                record = _ask(service, store, case, session_id)
                result = score(case, expected[case.id], record, catalog)
                results.append(result)
                verdict = "pass" if result.passed else "FAIL"
                print(
                    f"[{number:>2}/{len(cases)}] {verdict}  {case.id:<38} "
                    f"{result.latency_ms / 1000:5.1f}s"
                )
                if result.error and daily_quota_exhausted(result.error):
                    stopped_early = (
                        f"stopped after {number} of {len(cases)} cases: daily model quota spent"
                    )
                    print(stopped_early)
                    break
    finally:
        shutdown_tracing(tracer_provider)

    report = {
        "meta": {
            "label": args.label or args.version,
            "agent_version": args.version,
            "failure_modes": failures,
            "model": settings.llm_model,
            "session_id": session_id,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "stopped_early": stopped_early,
        },
        **report_sections(results),
    }
    json_path, md_path = write_run_report(report)
    summary = report["summary"]
    print(f"\npassed {summary['passed']}/{summary['cases']} · report {md_path} · data {json_path}")
    return 0


def _ask(service: AgentService, store: RunStore, case: GoldenCase, session_id: str) -> RunRecord:
    request = AskRequest(question=case.question, user_role=case.user_role, session_id=session_id)
    try:
        return service.ask(request, eval_case_id=case.id)
    except AgentRunError as exc:  # a crash is a result too: score the saved record
        return store.load(exc.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
