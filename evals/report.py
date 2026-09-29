"""Markdown + JSON reports for one eval run, and a comparison of two runs."""

import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).parent / "reports"

# key, label, higher is better, format
METRICS = [
    ("passed", "Cases passed", True, "count"),
    ("answer_accuracy", "Answer accuracy (data cases)", True, "share"),
    ("route_accuracy", "Route accuracy", True, "share"),
    ("output_type_accuracy", "Output type accuracy", True, "share"),
    ("sql_safety", "SQL safety (read-only, validates)", True, "share"),
    ("retries", "SQL retries", False, "count"),
    ("errors", "Crashed runs", False, "count"),
    ("provider_errors", "  of which model-API errors (503 etc.)", False, "count"),
    ("llm_calls", "Model calls", False, "count"),
    ("tokens", "Tokens", False, "count"),
    ("latency_p50_ms", "Latency p50", False, "ms"),
    ("latency_p95_ms", "Latency p95", False, "ms"),
]


def write_run_report(report: dict[str, Any]) -> tuple[Path, Path]:
    meta = report["meta"]
    stem = (
        REPORTS_DIR / f"{meta['started_at'][:19].replace('-', '').replace(':', '')}_{meta['label']}"
    )
    REPORTS_DIR.mkdir(exist_ok=True)
    json_path, md_path = stem.with_suffix(".json"), stem.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(render_run(report))
    return json_path, md_path


def render_run(report: dict[str, Any]) -> str:
    meta, summary, results = report["meta"], report["summary"], report["results"]
    lines = [
        f"# Eval report: {meta['label']}",
        "",
        f"{meta['started_at'][:16].replace('T', ' ')} UTC · agent {meta['agent_version']} · "
        f"failure modes: {meta['failure_modes']} · model {meta['model']} · "
        f"{summary['cases']} cases · session `{meta['session_id']}`",
        "",
        *(
            [f"> **Partial run:** {meta['stopped_early']}.", ""]
            if meta.get("stopped_early")
            else []
        ),
        "| Metric | Value |",
        "|---|---|",
        *[f"| {label} | {_value(key, fmt, summary)} |" for key, label, _, fmt in METRICS],
        "",
        "## By failure mode targeted",
        "",
        "| Targets | Passed |",
        "|---|---|",
        *[f"| {t} | {g['passed']}/{g['cases']} |" for t, g in sorted(report["by_target"].items())],
        "",
        "## Cases",
        "",
        "| Case | Targets | Route | Output | Answer | Retries | Latency | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        answer = "-" if r["answer_ok"] is None else _mark(r["answer_ok"])
        lines.append(
            f"| {r['case_id']} | {r['targets'] or '-'} "
            f"| {r['actual_route'] or '-'} {_mark(r['route_ok'])} "
            f"| {r['actual_output_type']} {_mark(r['output_type_ok'])} | {answer} | {r['retries']} "
            f"| {r['latency_ms'] / 1000:.1f} s | {'pass' if r['passed'] else '**fail**'} |"
        )
    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines += [
                f"### {r['case_id']} ({r['targets'] or 'baseline'})",
                "",
                f"> {r['question']}",
                "",
            ]
            lines += [f"- {problem}" for problem in problems(r)]
            lines += [
                f"- run `{r['run_id']}`"
                + (f" · [trace]({r['trace_url']})" if r["trace_url"] else ""),
                "",
            ]
    return "\n".join(lines) + "\n"


def render_comparison(a: dict[str, Any], b: dict[str, Any]) -> str:
    name_a, name_b = a["meta"]["label"], b["meta"]["label"]
    before = {r["case_id"]: r for r in a["results"]}
    after = {r["case_id"]: r for r in b["results"]}
    shared = [case for case in before if case in after]
    regressions = [c for c in shared if before[c]["passed"] and not after[c]["passed"]]
    fixed = [c for c in shared if not before[c]["passed"] and after[c]["passed"]]
    still_failing = [c for c in shared if not before[c]["passed"] and not after[c]["passed"]]

    lines = [f"# Eval comparison: {name_a} → {name_b}", ""]
    for report in (a, b):
        meta = report["meta"]
        lines.append(
            f"- **{meta['label']}**: agent {meta['agent_version']}, "
            f"failure modes {meta['failure_modes']}, "
            f"{meta['started_at'][:16].replace('T', ' ')} UTC"
        )
    lines += ["", f"## Regressions ({name_a} passed, {name_b} fails)", ""]
    lines += [f"- **{c}**: {'; '.join(problems(after[c]))}" for c in regressions] or ["None."]
    lines += [
        "",
        "## Metrics",
        "",
        f"| Metric | {name_a} | {name_b} | Change |",
        "|---|---|---|---|",
    ]
    for key, label, higher_is_better, fmt in METRICS:
        lines.append(
            f"| {label} | {_value(key, fmt, a['summary'])} | {_value(key, fmt, b['summary'])} "
            f"| {_change(a['summary'][key], b['summary'][key], fmt, higher_is_better)} |"
        )
    lines += [
        "",
        "## By failure mode targeted",
        "",
        f"| Targets | {name_a} | {name_b} |",
        "|---|---|---|",
    ]
    for target in sorted(set(a["by_target"]) | set(b["by_target"])):
        cells = [_fraction(report["by_target"].get(target)) for report in (a, b)]
        lines.append(f"| {target} | {cells[0]} | {cells[1]} |")
    lines += ["", f"## Fixed ({name_a} failed, {name_b} passes)", ""]
    lines += [
        f"- **{c}** ({before[c]['targets'] or 'baseline'}): was {'; '.join(problems(before[c]))}"
        for c in fixed
    ]
    lines += [] if fixed else ["None."]
    lines += ["", "## Failing in both", ""]
    lines += [f"- **{c}**: {'; '.join(problems(after[c]))}" for c in still_failing] or ["None."]
    lines += [
        "",
        "## Every case",
        "",
        f"| Case | Targets | {name_a} | {name_b} |",
        "|---|---|---|---|",
    ]
    for c in shared:
        lines.append(
            f"| {c} | {before[c]['targets'] or '-'} | {_result(before[c])} | {_result(after[c])} |"
        )
    return "\n".join(lines) + "\n"


def problems(result: dict[str, Any]) -> list[str]:
    found = []
    if not result["route_ok"]:
        found.append(f"route {result['actual_route']} (expected {result['expected_route']})")
    if not result["output_type_ok"]:
        expected = " or ".join(result["expected_output_type"])
        found.append(f"output {result['actual_output_type']} (expected {expected})")
    if result["answer_ok"] is False:
        found.append(f"answer wrong: {result['answer_detail']}")
    return found or ["passed"]


def _value(key: str, fmt: str, summary: dict[str, Any]) -> str:
    value = summary[key]
    if key == "passed":
        return f"{value}/{summary['cases']}"
    if value is None:
        return "n/a"
    return {"share": f"{value:.0%}", "count": f"{value:,}", "ms": f"{value / 1000:.1f} s"}[fmt]


def _change(before: float | None, after: float | None, fmt: str, higher_is_better: bool) -> str:
    if before is None or after is None or before == after:
        return "-"
    delta = after - before
    text = {
        "share": f"{delta * 100:+.0f} pts",
        "count": f"{delta:+,}",
        "ms": f"{delta / 1000:+.1f} s",
    }[fmt]
    return f"{text} ({'better' if (delta > 0) == higher_is_better else 'worse'})"


def _fraction(group: dict[str, int] | None) -> str:
    return f"{group['passed']}/{group['cases']}" if group else "-"


def _result(result: dict[str, Any]) -> str:
    return "pass" if result["passed"] else f"fail: {'; '.join(problems(result))}"


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"
