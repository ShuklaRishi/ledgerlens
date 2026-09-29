"""Decide how to handle the question: a defined metric, custom SQL, clarify, or out of scope."""

from typing import Any

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.llm import ask_structured
from ledgerlens.agent.prompts import render_prompt
from ledgerlens.agent.state import AgentState, RouteDecision


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    names = [n for n in state["context"].metric_names if n in deps.layer.metrics]
    prompt = render_prompt(
        deps.prompt_version("route"),  # v1's prompt: "try to answer every question"
        "route",
        metrics="\n".join(f"- {deps.layer.metrics[n].summary()}" for n in names) or "(none)",
        question=state["question"],
    )
    decision = ask_structured(deps.llm, RouteDecision, prompt)
    if decision.metric not in deps.layer.metrics:  # the model named something we don't define
        decision = decision.model_copy(update={"metric": None})
    return {"route": decision}
