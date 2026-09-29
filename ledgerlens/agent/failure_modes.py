"""The agent's known failure modes, switchable so both versions run from one codebase.

AGENT_VERSION=v1 is the agent as first shipped: every failure mode on. v2 is the fixed agent.
FAILURE_MODE puts single modes back into v2, to study one failure at a time:

    FAILURE_MODE=date_boundary make ask Q="What was revenue last month?"

Each mode is a realistic cause (a prompt missing a rule, a missing check, the machine clock),
never a hard-coded wrong answer. Prompt-level causes are the files in prompts/v1/.
"""

from enum import StrEnum


class FailureMode(StrEnum):
    FANOUT_JOIN = "fanout_join"  # planner prompt has no grain rule; no fan-out check
    SKIPPED_VISUALISATION = "skipped_visualisation"  # "be concise": the model decides on charts
    HALLUCINATED_COLUMN = "hallucinated_column"  # top-3 tables, no join paths; no column check
    DATE_BOUNDARY = "date_boundary"  # relative dates anchored to the machine clock
    WRONG_ROUTE = "wrong_route"  # router prompt: "try to answer every question"


# The prompt each prompt-level mode lives in: the v1 file while it's on, v2 once fixed.
PROMPT_FAILURE_MODES = {
    "route": FailureMode.WRONG_ROUTE,
    "plan_sql": FailureMode.FANOUT_JOIN,
    "answer": FailureMode.SKIPPED_VISUALISATION,
}


def active_failure_modes(agent_version: str, failure_mode: str) -> frozenset[FailureMode]:
    """Raises ValueError on an unknown version or mode, so a typo fails at startup."""
    if agent_version == "v1" or failure_mode == "all":
        return frozenset(FailureMode)
    if agent_version != "v2":
        raise ValueError(f"AGENT_VERSION must be v1 or v2, got {agent_version!r}")
    names = [name.strip() for name in failure_mode.split(",")]
    try:
        return frozenset(FailureMode(name) for name in names if name and name != "none")
    except ValueError as exc:
        valid = ", ".join(mode.value for mode in FailureMode)
        raise ValueError(f"FAILURE_MODE must be none, all, or a comma list of: {valid}") from exc


def prompt_version(prompt: str, active: frozenset[FailureMode]) -> str:
    return "v1" if PROMPT_FAILURE_MODES.get(prompt) in active else "v2"


def label(active: frozenset[FailureMode]) -> str:
    """'none' or a sorted comma list, for run records and trace metadata."""
    return ",".join(sorted(active)) or "none"
