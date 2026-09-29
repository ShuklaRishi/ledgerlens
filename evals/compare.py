"""Compare two eval reports: metrics side by side, and every case that flipped.

uv run python -m evals.compare --latest v1 v2     # newest report for each label
uv run python -m evals.compare evals/reports/A.json evals/reports/B.json
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.report import REPORTS_DIR, render_comparison


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.compare", description="Compare two eval reports.")
    parser.add_argument("reports", nargs="*", help="two report .json files: before, after")
    parser.add_argument("--latest", nargs=2, metavar=("BEFORE", "AFTER"), help="labels, e.g. v1 v2")
    args = parser.parse_args(argv)

    paths = (
        [_latest(name) for name in args.latest] if args.latest else [Path(p) for p in args.reports]
    )
    if len(paths) != 2:
        parser.error("give two report files, or --latest BEFORE AFTER")
    before, after = (_load(path) for path in paths)

    markdown = render_comparison(before, after)
    out = REPORTS_DIR / (
        f"{datetime.now(UTC):%Y%m%dT%H%M%S}_compare_{before['meta']['label']}_vs_{after['meta']['label']}.md"
    )
    out.write_text(markdown)
    print(markdown)
    print(f"written to {out}")
    return 0


def _latest(label: str) -> Path:
    matches = sorted(REPORTS_DIR.glob(f"*_{label}.json"))
    if not matches:
        raise SystemExit(f"no report for {label!r} in {REPORTS_DIR}; run `make eval-{label}` first")
    return matches[-1]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


if __name__ == "__main__":
    raise SystemExit(main())
