"""Versioned prompts: prompts/<agent_version>/<name>.md, filled with string.Template ($name)."""

from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent


def render_prompt(version: str, name: str, **values: object) -> str:
    template = Template((PROMPTS_DIR / version / f"{name}.md").read_text())
    return template.substitute({key: str(value) for key, value in values.items()})
