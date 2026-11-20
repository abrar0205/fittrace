"""Engineering specification limits for a gap measurement location.

Specification limits (LSL/USL) are design requirements. They are *not* the same
as statistical process-control limits, which describe the process' own
variation (see ``fittrace.analytics.spc``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToleranceStatus(StrEnum):
    IN_TOLERANCE = "in_tolerance"
    OUT_LOW = "out_low"
    OUT_HIGH = "out_high"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True)
class ToleranceSpec:
    nominal_mm: float
    lower_tol_mm: float  # negative, e.g. -0.5
    upper_tol_mm: float  # positive, e.g. +0.5

    def __post_init__(self) -> None:
        if self.lower_tol_mm > 0 or self.upper_tol_mm < 0:
            raise ValueError("lower_tol_mm must be <= 0 and upper_tol_mm >= 0")

    @property
    def lsl(self) -> float:
        return self.nominal_mm + self.lower_tol_mm

    @property
    def usl(self) -> float:
        return self.nominal_mm + self.upper_tol_mm

    def evaluate(self, gap_mm: float | None) -> tuple[ToleranceStatus, float | None]:
        """Return (status, deviation_from_nominal_mm)."""
        if gap_mm is None:
            return ToleranceStatus.NOT_EVALUABLE, None
        dev = gap_mm - self.nominal_mm
        if gap_mm < self.lsl:
            return ToleranceStatus.OUT_LOW, dev
        if gap_mm > self.usl:
            return ToleranceStatus.OUT_HIGH, dev
        return ToleranceStatus.IN_TOLERANCE, dev
