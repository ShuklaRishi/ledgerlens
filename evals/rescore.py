"""Re-score saved eval reports from their run records, without calling the model.

    uv run python -m evals.rescore evals/reports/20260928T141239_v1.json

When the scoring rules change, the agent's answers are still in runs/<run_id>/run.json:
rescoring rewrites the report in place and costs no model quota.
"""

import argparse
import json
from pathlib import Path

from evals.cases import expected_rows, load_cases
from evals.report import write_run_report
from evals.scoring import by_target, score, summarize
from ledgerlens.core.config import get_settings
from ledgerlens.db.connection import connect_agent
from ledgerlens.services.run_store import RunStore
from ledgerlens.sql.catalog import load_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.rescore", description="Re-score saved reports.")
    parser.add_argument("reports", nargs="+", type=Path, help="report .json files")
    args = parser.parse_args(argv)

    settings = get_settings()
    store = RunStore(settings.runs_dir)
    cases = {case.id: case for case in load_cases()}
    with connect_agent(settings) as conn:
        catalog = load_catalog(conn)
        for path in args.reports:
            report = json.loads(path.read_text())
            results = []
            for saved in report["results"]:
                case = cases[saved["case_id"]]
                record = store.load(saved["run_id"])
                results.append(score(case, expected_rows(conn, case), record, catalog))
            report["summary"] = summarize(results)
            report["by_target"] = by_target(results)
            report["results"] = [result.model_dump() for result in results]
            _, md_path = write_run_report(report)
            print(f"{path.name}: passed {report['summary']['passed']}/{len(results)} -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
