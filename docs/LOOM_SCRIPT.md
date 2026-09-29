# Loom script (3 minutes)

**Before recording:** `make up`, `make api`, `make ui`, and open these tabs:
1. the UI with the flagged v1 run: `http://localhost:8501/?run=20260928T141548-b21433`
2. Phoenix: `http://localhost:6006/redirects/traces/d906fb59530781b74926a1b2a065fdf8`
3. the comparison report `evals/reports/20260929T072346_compare_v1_vs_v2.md` (rendered, e.g. in VS Code)
4. `ledgerlens/agent/nodes/resolve_dates.py` in the editor

Opening a saved run with `?run=` means no waiting on the free-tier model while recording.
Keep `.env` off screen. Font size up.

---

### 0:00–0:20 · The problem

**Screen:** README, the graph diagram.

> "At work I run an analytics agent in Slack: account managers and leadership ask it
> business questions, it writes SQL and posts charts. The failure that hurts isn't a crash,
> it's a confident wrong number. This is a public replica of that kind of agent, on a sample
> DVD-rental database, built so every answer can be traced back to its cause."

### 0:20–1:00 · A business user flags a bad answer

**Screen:** tab 1, the chat UI.

> "Here's the first version of the agent. Leadership asks: what was revenue last month? It
> says there was no revenue. That's wrong: June was a normal month. So they do what a
> business user can do: thumbs down, and a sentence about why."

Click 👎, type the comment, send. Point at "attached to the trace".

> "That feedback is now attached to the exact trace of this run."

### 1:00–2:00 · The developer opens the trace

**Screen:** tab 2, Phoenix.

> "This is the trace. The thumbs-down is on the root span, with the comment. One span per
> step: retrieval, routing, dates, planning, SQL validation, execution, sanity checks,
> chart, answer. Only three of them call the model."

Click through, one sentence each:
- `resolve_dates`: "the anchor came from **today's date**, September 2026."
- `plan_sql`: "so the plan filters payments for **August 2026**."
- `execute_sql`: "zero rows. The data ends in July 2022."
- `check_result`: "the sanity check even warned: empty result. v1 turned that into a confident 'no revenue'."

> "Root cause in one trace: relative dates resolved against the server clock instead of the
> data. No re-running, no guessing."

### 2:00–2:30 · The fix, proved with evals

**Screen:** tab 4, then tab 3.

> "The fix is a few lines: anchor relative dates to the latest date in the data, and tell
> the user how 'last month' was resolved. Then the evals: twenty golden questions with
> hand-written SQL as ground truth, run against both versions."

> "v1 passed 7 of 20, v2 passes all 20. The date cases went from none of three to all
> three, with no regressions. And the evals earned their keep: v2's first run caught a new
> bug, a join that inflated a customer's value 599 times, before any user saw it."

### 2:30–3:00 · What I'd build next at Neatlogs

**Screen:** Phoenix trace list, or back to camera.

> "Three things I wanted while doing this:
> one, a trace summary that names the span that caused the failure: 'resolve_dates anchored
> to today, but the data ends in 2022';
> two, comparing the same eval case across two versions side by side, prompt diff and SQL diff;
> three, a one-click way to turn a thumbs-down into a regression test in the golden set.
> That's the loop Neatlogs is built for, and I'd love to build it."
