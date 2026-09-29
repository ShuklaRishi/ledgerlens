"""Ledgerlens chat for business users: a thin client over the FastAPI service.

    make api    # terminal 1
    make ui     # terminal 2, then open http://localhost:8501

All logic lives in the API; this file only renders what it returns. Open a saved run with
?run=<run_id> (no model call), e.g. to look at a run someone flagged.
"""

import os
import uuid
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from ledgerlens.sql.executor import is_number
from ledgerlens.viz.charts import format_value, pretty

API_URL = os.environ.get("LEDGERLENS_API_URL", "http://localhost:8000")
ROLES = {"leadership": "Leadership", "am": "Account manager", "sales": "Sales", "dev": "Developer"}
EXAMPLES = [
    "What was revenue by store last month?",
    "How has monthly revenue trended this year?",
    "Which 5 film categories earned the most in June 2022?",
    "How many customers are there in each country? Top 5.",
]

Run = dict[str, Any]


@st.cache_resource
def api() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=300)  # free-tier model calls can be slow


def main() -> None:
    st.set_page_config(page_title="Ledgerlens", page_icon="📊")
    st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])
    st.session_state.setdefault("runs", [])
    st.session_state.setdefault("feedback_sent", {})
    role = sidebar()
    open_linked_run()

    st.title("Ledgerlens")
    st.caption("Ask about the DVD-rental business: revenue, rentals, customers, films and stores.")
    for run in st.session_state.runs:
        show_turn(run)

    if question := st.chat_input("Ask a question, e.g. " + EXAMPLES[0]):
        with st.chat_message("user"):
            st.write(question)
        with (
            st.chat_message("assistant"),
            st.spinner("Finding the data, writing SQL, checking the result..."),
        ):
            run = ask(question, role)
        if run:
            st.session_state.runs.append(run)
            st.rerun()


def sidebar() -> str:
    with st.sidebar:
        role = st.selectbox("You are", list(ROLES), format_func=ROLES.get)
        st.caption(f"Conversation `{st.session_state.session_id}`")
        if st.button("New conversation"):
            st.session_state.session_id = uuid.uuid4().hex[:12]
            st.session_state.runs = []
            st.query_params.clear()
            st.rerun()
        st.divider()
        st.markdown("**Try asking**")
        for example in EXAMPLES:
            st.caption(example)
        st.divider()
        st.caption(f"API: {API_URL}")
    return role


def open_linked_run() -> None:
    run_id = st.query_params.get("run")
    already_open = any(run["run_id"] == run_id for run in st.session_state.runs)
    if run_id and not already_open and (run := fetch_run(run_id)):
        st.session_state.runs.append(run)


def ask(question: str, role: str) -> Run | None:
    payload = {"question": question, "user_role": role, "session_id": st.session_state.session_id}
    try:
        response = api().post("/v1/ask", json=payload)
    except httpx.HTTPError as exc:
        st.error(f"Can't reach the Ledgerlens API at {API_URL} ({exc}). Is `make api` running?")
        return None
    if not response.headers.get("content-type", "").startswith("application/json"):
        st.error(f"The API returned {response.status_code}: {response.text[:300]}")
        return None
    body = response.json()
    if response.status_code == 500 and "run_id" in body:  # the agent crashed; its run was saved
        return fetch_run(body["run_id"])
    if response.status_code != 200:
        st.error(f"The API said: {body.get('detail', response.text)}")
        return None
    return body


def fetch_run(run_id: str) -> Run | None:
    try:
        response = api().get(f"/v1/runs/{run_id}")
    except httpx.HTTPError as exc:
        st.error(f"Can't reach the Ledgerlens API at {API_URL} ({exc}).")
        return None
    if response.status_code != 200:
        st.error(f"Run {run_id} not found.")
        return None
    return response.json()


def escape_dollars(text: str) -> str:
    """Keep $ literal in Markdown: Streamlit renders text between two $ signs as LaTeX."""
    return text.replace("$", r"\$")


def show_turn(run: Run) -> None:
    with st.chat_message("user"):
        st.markdown(escape_dollars(run["question"]))
    with st.chat_message("assistant"):
        show_answer(run)
        show_details(run)
        show_feedback(run)


def show_answer(run: Run) -> None:
    answer = run.get("answer")
    if run["status"] == "error" or answer is None:
        st.error(
            "Something went wrong on our side. The run was saved so the team can look into it."
        )
        return
    st.markdown(f"**{escape_dollars(answer['headline'])}**")
    if answer.get("interpretation"):
        st.markdown(escape_dollars(answer["interpretation"]))
    show_result(run)
    for warning in answer.get("warnings", []):
        st.warning(escape_dollars(warning), icon="⚠️")
    notes = [note for note in (answer.get("definition"), answer.get("timeframe")) if note]
    if notes:
        st.caption(escape_dollars("  \n".join(notes)))


def show_result(run: Run) -> None:
    result, output = run.get("result"), run.get("output_type")
    if not result or not result["rows"]:
        return
    columns, rows = result["columns"], result["rows"]
    if output in ("line", "bar"):
        st.image(f"{API_URL}/v1/runs/{run['run_id']}/chart.png")  # the browser fetches it
    elif output == "stat":
        measure = next(
            (
                i
                for i in reversed(range(len(columns)))
                if is_number(rows[0][i]) and not columns[i].endswith("_id")
            ),
            len(columns) - 1,
        )
        st.metric(pretty(columns[measure]), format_value(columns[measure], rows[0][measure]))
    elif output == "table":
        st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True)


def show_details(run: Run) -> None:
    with st.expander("How I got this"):
        route = run.get("route") or {}
        st.markdown(
            f"**Route:** {route.get('route', '-')}: {escape_dollars(route.get('reason', ''))}"
        )
        if retrieved := run.get("retrieved"):
            metrics = ", ".join(
                f"{hit['name']} ({hit['score']:.2f})" for hit in retrieved["metrics"]
            )
            st.markdown(f"**Definitions considered:** {metrics}")
        if run.get("plan"):
            st.markdown(f"**Plan:** {escape_dollars(run['plan'])}")
        if run.get("sql"):
            st.code(run["sql"], language="sql")
        for attempt in run.get("attempts", []):
            if attempt["errors"]:
                errors = escape_dollars("; ".join(attempt["errors"]))
                st.caption(f"Attempt {attempt['attempt']} ({attempt['stage']}) rejected: {errors}")
        if run.get("error"):
            st.caption(escape_dollars(f"Error: {run['error']}"))
        usage = run["usage"]
        tokens = usage["input_tokens"] + usage["output_tokens"]
        st.caption(
            f"run `{run['run_id']}` · {usage['llm_calls']} model calls · {tokens:,} tokens · "
            f"{run['latency_ms'] / 1000:.1f}s"
        )
        if run.get("trace_url"):
            st.markdown(f"[Open the trace in Phoenix]({run['trace_url']})")


def show_feedback(run: Run) -> None:
    run_id, sent = run["run_id"], st.session_state.feedback_sent
    if run_id in sent:
        st.caption(sent[run_id])
        return
    rating = st.feedback("thumbs", key=f"rating-{run_id}")  # 0 = thumbs down, 1 = thumbs up
    if rating is None:
        return
    prompt = "What was wrong or missing?" if rating == 0 else "Anything to add? (optional)"
    comment = st.text_input(prompt, key=f"comment-{run_id}")
    if st.button("Send feedback", key=f"send-{run_id}"):
        payload = {"rating": "up" if rating == 1 else "down", "comment": comment or None}
        response = api().post(f"/v1/runs/{run_id}/feedback", json=payload)
        if response.status_code != 200:
            st.error("Couldn't send feedback, please try again.")
            return
        attached = response.json()["attached_to_trace"]
        sent[run_id] = "Thanks, feedback sent" + (
            " and attached to the trace." if attached else "."
        )
        st.rerun()


main()
