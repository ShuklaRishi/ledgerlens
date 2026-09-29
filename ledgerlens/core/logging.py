"""Logging setup. Every line carries the run_id of the agent run it belongs to ('-' outside one)."""

import logging
from contextvars import ContextVar

run_id_var: ContextVar[str] = ContextVar("run_id", default="-")


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RunIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s run=%(run_id)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
