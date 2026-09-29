"""`ledgerlens` command line. Calls the same services the API uses; no HTTP involved."""

import argparse
from textwrap import indent
from typing import get_args

import psycopg

from ledgerlens.agent.state import UserRole
from ledgerlens.core.config import get_settings
from ledgerlens.core.logging import setup_logging
from ledgerlens.core.tracing import setup_tracing, shutdown_tracing
from ledgerlens.db.check import DbCheckReport, run_checks
from ledgerlens.db.connection import create_agent_pool
from ledgerlens.schemas.ask import AskRequest
from ledgerlens.schemas.run import RunRecord
from ledgerlens.semantic.embedder import Embedder
from ledgerlens.semantic.seed import seed
from ledgerlens.services.agent_service import AgentRunError, AgentService
from ledgerlens.services.run_store import RunStore
from ledgerlens.viz.charts import format_table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerlens")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("db-check", help="verify Pagila is loaded and agent_ro cannot write")
    commands.add_parser("seed", help="embed the semantic layer into pgvector (local model, no API)")
    ask = commands.add_parser("ask", help="answer a business question")
    ask.add_argument("question")
    ask.add_argument("--role", choices=get_args(UserRole), default="dev")
    ask.add_argument("--session", default=None, help="group turns of one conversation")
    ask.add_argument("-v", "--verbose", action="store_true", help="show the agent's logs")
    args = parser.parse_args(argv)

    try:
        if args.command == "db-check":
            return _db_check()
        if args.command == "seed":
            return _seed()
        return _ask(args.question, args.role, args.session, args.verbose)
    except psycopg.OperationalError as exc:
        print(f"cannot reach the database: {exc}\nIs it up? Try `make up`.")
        return 1


def _db_check() -> int:
    report = run_checks(get_settings())
    _print_report(report)
    return 0 if report.ok else 1


def _seed() -> int:
    settings = get_settings()
    count = seed(settings, Embedder(settings.embedding_model, settings.cache_dir))
    print(f"seeded {count} documents into semantic.docs")
    return 0


def _ask(question: str, role: UserRole, session: str | None, verbose: bool) -> int:
    settings = get_settings()
    setup_logging("INFO" if verbose else "CRITICAL")  # failures are summarised below either way
    tracer_provider = setup_tracing(settings)
    store = RunStore(settings.runs_dir)
    try:
        with create_agent_pool(settings) as pool:
            service = AgentService(settings, pool, store)
            request = AskRequest(question=question, user_role=role, session_id=session)
            record = service.ask(request)
    except AgentRunError as exc:
        print(
            f"The agent failed: {exc}\nFull record: {settings.runs_dir / exc.run_id / 'run.json'}"
        )
        return 1
    finally:
        shutdown_tracing(tracer_provider)  # a one-shot process must flush before exiting
    _print_run(record)
    return 0


def _print_run(record: RunRecord) -> None:
    answer = record.answer
    assert answer is not None
    print(answer.headline)
    if answer.interpretation:
        print(answer.interpretation)
    print()
    details = [("definition", answer.definition), ("timeframe", answer.timeframe)]
    details += [("warning", w) for w in answer.warnings]
    if record.output_type:
        details.append(
            (
                "output",
                f"{record.output_type} chart: {record.chart_path}"
                if record.chart_path
                else record.output_type,
            )
        )
    for label, value in details:
        if value:
            print(f"  {label:<11}{value}")
    if record.result and record.output_type == "table":
        print(indent(format_table(record.result, limit=10), "    "))
    if record.sql:
        print(f"\n  plan\n{indent(record.plan or '', '    ')}\n  sql\n{indent(record.sql, '    ')}")
    attempts = len({a.attempt for a in record.attempts})
    route = record.route.route if record.route else "-"
    tokens = record.usage.input_tokens + record.usage.output_tokens
    print(
        f"\nrun {record.run_id} | route {route} | sql attempts {attempts} | "
        f"{record.usage.llm_calls} LLM calls | {tokens:,} tokens | {record.latency_ms / 1000:.1f}s"
    )
    if record.trace_id:
        print(f"trace {record.trace_url or record.trace_id}")


def _print_report(report: DbCheckReport) -> None:
    print(f"postgres {report.server_version} | pgvector {report.pgvector_version or 'MISSING'}")
    print("rows:   " + " | ".join(f"{t} {n:,}" for t, n in report.row_counts.items()))
    for column, (low, high) in report.date_ranges.items():
        print(f"range:  {column} {low:%Y-%m-%d} -> {high:%Y-%m-%d}")
    print("agent_ro privilege probes (read-only flag turned OFF, so only grants can stop them):")
    for probe in report.probes:
        print(f"  {'ok  ' if probe.ok else 'FAIL'} {probe.name:<22} {probe.detail}")
    print("OK" if report.ok else "FAILED")
