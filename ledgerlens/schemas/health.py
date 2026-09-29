from typing import Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    name: str
    ok: bool
    critical: bool
    detail: str


class HealthReport(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checks: list[CheckResult]

    @classmethod
    def from_checks(cls, checks: list[CheckResult]) -> "HealthReport":
        if any(c.critical and not c.ok for c in checks):
            status = "down"
        elif all(c.ok for c in checks):
            status = "ok"
        else:
            status = "degraded"
        return cls(status=status, checks=checks)
