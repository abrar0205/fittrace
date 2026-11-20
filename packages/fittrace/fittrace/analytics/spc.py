"""Individuals and moving-range (I-MR) control charts with applicability checks.

Control limits describe the *process* (its own short-term variation, estimated
from the average moving range of a baseline window). They are independent of
engineering specification limits. Limits are estimated from a baseline window
(Phase I) and then applied to all points (Phase II); estimating them from data
that already contains a shift would widen the limits and hide the shift.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

D2_N2 = 1.128  # unbiasing constant for moving ranges of span 2
D4_N2 = 3.267


def _runs_same_side(x: np.ndarray, center: float, run: int) -> np.ndarray:
    flags = np.zeros(len(x), dtype=bool)
    side = np.sign(x - center)
    count, prev = 0, 0.0
    for i, s in enumerate(side):
        count = count + 1 if (s == prev and s != 0) else (1 if s != 0 else 0)
        prev = s
        if count >= run:
            flags[i - run + 1 : i + 1] = True
    return flags


def _two_of_three_beyond_2s(x: np.ndarray, center: float, sigma: float) -> np.ndarray:
    flags = np.zeros(len(x), dtype=bool)
    up = x > center + 2 * sigma
    dn = x < center - 2 * sigma
    for i in range(2, len(x)):
        for side in (up, dn):
            w = side[i - 2 : i + 1]
            if w.sum() >= 2:
                flags[i - 2 : i + 1] |= w
    return flags


def imr_chart(values: np.ndarray | list[float], baseline_n: int | None = None) -> dict:
    """Compute I-MR limits from the first ``baseline_n`` points and evaluate rules.

    Rules (Western Electric): R1 a point beyond 3 sigma; R2 two of three
    consecutive points beyond 2 sigma on the same side; R4 eight consecutive
    points on one side of the centre line.
    """
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2:
        return {"applicable": False, "warnings": ["fewer than 2 points"], "n": n}
    b = min(n, baseline_n or n)
    base = x[:b]
    mr = np.abs(np.diff(x))
    mr_base = np.abs(np.diff(base))
    center = float(base.mean())
    mr_bar = float(mr_base.mean()) if len(mr_base) else float("nan")
    sigma = mr_bar / D2_N2
    ucl, lcl = center + 3 * sigma, center - 3 * sigma
    warnings: list[str] = []
    if b < 20:
        warnings.append(f"baseline has {b} points; at least 20 are recommended for I-MR limits")
    r1 = None
    if b >= 3:
        r1 = float(np.corrcoef(base[:-1], base[1:])[0, 1])
        if abs(r1) > 0.3:
            warnings.append(f"baseline lag-1 autocorrelation {r1:.2f}: I-MR limits assume independent points")
    normal_p = None
    if 8 <= b <= 5000:
        normal_p = float(stats.shapiro(base).pvalue)
        if normal_p < 0.01:
            warnings.append(f"baseline deviates from normality (Shapiro-Wilk p={normal_p:.3g}); rule false-alarm rates differ")
    base_out = int(np.sum((base > ucl) | (base < lcl)))
    if base_out:
        warnings.append(f"{base_out} baseline points fall outside the limits; baseline may not be in control")

    rule1 = (x > ucl) | (x < lcl)
    rule2 = _two_of_three_beyond_2s(x, center, sigma)
    rule4 = _runs_same_side(x, center, 8)
    mr_ucl = D4_N2 * mr_bar
    first_signal = None
    for i in range(b, n):
        if rule1[i] or rule2[i] or rule4[i]:
            first_signal = i
            break
    return {
        "applicable": b >= 20,
        "n": n,
        "baseline_n": b,
        "center": center,
        "sigma_hat": sigma,
        "ucl": ucl,
        "lcl": lcl,
        "mr_bar": mr_bar,
        "mr_ucl": mr_ucl,
        "moving_range": [None, *mr.tolist()],
        "rule1": rule1.tolist(),
        "rule2": rule2.tolist(),
        "rule4": rule4.tolist(),
        "mr_out": [False, *(mr > mr_ucl).tolist()],
        "first_signal_index": first_signal,
        "lag1_autocorrelation": r1,
        "shapiro_p": normal_p,
        "warnings": warnings,
    }


def capability(values: np.ndarray | list[float], lsl: float, usl: float, sigma_within: float) -> dict:
    """Cp/Cpk from within-subgroup sigma. Only meaningful for a stable process."""
    x = np.asarray(values, dtype=float)
    mu = float(x.mean())
    if not math.isfinite(sigma_within) or sigma_within <= 0:
        return {"cp": None, "cpk": None, "mean": mu}
    cp = (usl - lsl) / (6 * sigma_within)
    cpk = min(usl - mu, mu - lsl) / (3 * sigma_within)
    return {"cp": float(cp), "cpk": float(cpk), "mean": mu}
