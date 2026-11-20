"""Candidate-contributor ranking for a dimensional mean shift.

Method ``fittrace.contributors.did-attribution`` (docs/methodology.md):

Given units in production order, a target deviation series and a change index
``k`` (first unit of the shifted regime), every candidate factor is tested with
an ordinary-least-squares model with heteroscedasticity-robust (HC3) errors:

* categorical level L of factor F (e.g. ``S20 fixture = FX-202``)::

      y = b0 + b1*post + b2*[F=L] + b3*post*[F=L] + e

  ``b3`` is the difference-in-differences effect: how much more the level
  changed than the rest of the population across the change point.
  Attributable shift = ``share_post(L) * b3``.

* continuous parameter X::

      y = b0 + b1*post + b2*X + e

  Attributable shift = ``b2 * (mean_post(X) - mean_pre(X))``.

``explained_fraction = attributable_shift / observed_shift``. p-values are
adjusted with Benjamini-Hochberg across all tested hypotheses. Hypotheses are
ranked by ``explained_fraction`` among those with ``q < alpha`` and the effect
in the direction of the observed shift, then the rest.

This is association analysis on observational data. A high rank means
"consistent with the data and worth checking", never "confirmed root cause".
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

METHOD = "fittrace.contributors.did-attribution"
METHOD_VERSION = "1.0.0"


@dataclass
class Hypothesis:
    factor_type: str  # "equipment" | "categorical" | "parameter"
    factor: str
    level: str | None
    station: str | None
    status: str  # "tested" | "not_estimable"
    effect_mm: float | None = None
    ci95: tuple[float, float] | None = None
    p_value: float | None = None
    q_value: float | None = None
    attributable_shift_mm: float | None = None
    explained_fraction: float | None = None
    n_pre: int = 0
    n_post: int = 0
    significant: bool = False
    rank: int | None = None
    reason: str | None = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.ci95 is not None:
            d["ci95"] = list(self.ci95)
        return d


def _ols_hc3(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    h = np.einsum("ij,jk,ik->i", X, xtx_inv, X)
    w = (resid / np.clip(1.0 - h, 1e-8, None)) ** 2
    cov = xtx_inv @ (X.T * w) @ X @ xtx_inv
    return beta, np.sqrt(np.clip(np.diag(cov), 0, None))


def benjamini_hochberg(p: list[float]) -> list[float]:
    p_arr = np.asarray(p, dtype=float)
    m = len(p_arr)
    if m == 0:
        return []
    order = np.argsort(p_arr)
    ranked = p_arr[order] * m / (np.arange(m) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.clip(q, 0, 1)
    return out.tolist()


def cramers_v(a: pd.Series, b: pd.Series) -> float:
    tab = pd.crosstab(a, b).to_numpy()
    if tab.shape[0] < 2 or tab.shape[1] < 2:
        return float("nan")
    chi2 = stats.chi2_contingency(tab, correction=False)[0]
    n = tab.sum()
    return float(math.sqrt(chi2 / (n * (min(tab.shape) - 1))))


def rank_contributors(
    df: pd.DataFrame,
    target: str,
    change_index: int,
    categorical: dict[str, str | None],
    continuous: dict[str, str | None],
    alpha: float = 0.05,
    min_group: int = 5,
) -> dict:
    """Rank candidate contributors.

    ``df`` must be in production order. ``categorical`` / ``continuous`` map a
    column name to the station it belongs to (or ``None``).
    """
    n = len(df)
    y = df[target].to_numpy(dtype=float)
    post = (np.arange(n) >= change_index).astype(float)
    n_pre, n_post = int((post == 0).sum()), int(post.sum())
    observed = float(y[post == 1].mean() - y[post == 0].mean()) if n_pre and n_post else float("nan")
    hyps: list[Hypothesis] = []

    for col, station in categorical.items():
        ftype = "equipment" if station else "categorical"
        for level in sorted(df[col].dropna().unique().tolist()):
            ind = (df[col] == level).to_numpy(dtype=float)
            npre_l, npost_l = int(((post == 0) & (ind == 1)).sum()), int(((post == 1) & (ind == 1)).sum())
            npre_o, npost_o = int(((post == 0) & (ind == 0)).sum()), int(((post == 1) & (ind == 0)).sum())
            h = Hypothesis(ftype, col, str(level), station, "tested", n_pre=npre_l, n_post=npost_l)
            if min(npre_l, npost_l, npre_o, npost_o) < min_group:
                h.status = "not_estimable"
                h.reason = (
                    f"needs >= {min_group} units in each of level/rest x before/after; "
                    f"have {npre_l}/{npost_l} (level) and {npre_o}/{npost_o} (rest). "
                    "A level that exists only on one side of the change is confounded with time."
                )
                hyps.append(h)
                continue
            X = np.column_stack([np.ones(n), post, ind, post * ind])
            beta, se = _ols_hc3(X, y)
            b3, s3 = float(beta[3]), float(se[3])
            dof = n - X.shape[1]
            p = float(2 * stats.t.sf(abs(b3) / s3, dof)) if s3 > 0 else 1.0
            tcrit = float(stats.t.ppf(0.975, dof))
            share = npost_l / max(1, n_post)
            h.effect_mm = b3
            h.ci95 = (b3 - tcrit * s3, b3 + tcrit * s3)
            h.p_value = p
            h.attributable_shift_mm = share * b3
            h.evidence = {
                "model": "y ~ post + level + post:level (OLS, HC3)",
                "mean_pre_level": float(y[(post == 0) & (ind == 1)].mean()),
                "mean_post_level": float(y[(post == 1) & (ind == 1)].mean()),
                "mean_pre_rest": float(y[(post == 0) & (ind == 0)].mean()),
                "mean_post_rest": float(y[(post == 1) & (ind == 0)].mean()),
                "share_post": share,
            }
            hyps.append(h)

    for col, station in continuous.items():
        xcol = df[col].to_numpy(dtype=float)
        ok = np.isfinite(xcol)
        h = Hypothesis("parameter", col, None, station, "tested", n_pre=int((ok & (post == 0)).sum()),
                       n_post=int((ok & (post == 1)).sum()))
        if h.n_pre < min_group or h.n_post < min_group or np.nanstd(xcol) == 0:
            h.status, h.reason = "not_estimable", "insufficient data or no variation"
            hyps.append(h)
            continue
        X = np.column_stack([np.ones(ok.sum()), post[ok], xcol[ok]])
        beta, se = _ols_hc3(X, y[ok])
        b2, s2 = float(beta[2]), float(se[2])
        dof = int(ok.sum()) - 3
        p = float(2 * stats.t.sf(abs(b2) / s2, dof)) if s2 > 0 else 1.0
        dx = float(np.nanmean(xcol[post == 1]) - np.nanmean(xcol[post == 0]))
        tcrit = float(stats.t.ppf(0.975, dof))
        h.effect_mm = b2  # mm per unit of parameter
        h.ci95 = (b2 - tcrit * s2, b2 + tcrit * s2)
        h.p_value = p
        h.attributable_shift_mm = b2 * dx
        h.evidence = {
            "model": "y ~ post + x (OLS, HC3)",
            "slope_mm_per_unit": b2,
            "mean_pre_x": float(np.nanmean(xcol[post == 0])),
            "mean_post_x": float(np.nanmean(xcol[post == 1])),
            "delta_x": dx,
            "spearman_rho": float(stats.spearmanr(xcol[ok], y[ok]).statistic),
        }
        hyps.append(h)

    tested = [h for h in hyps if h.status == "tested"]
    qs = benjamini_hochberg([h.p_value for h in tested])  # type: ignore[misc]
    for h, q in zip(tested, qs, strict=True):
        h.q_value = q
        if math.isfinite(observed) and abs(observed) > 1e-12:
            h.explained_fraction = (h.attributable_shift_mm or 0.0) / observed
        h.significant = bool(q < alpha and (h.explained_fraction or 0) > 0)

    tested.sort(key=lambda h: (not h.significant, -(h.explained_fraction or -1e9)))
    for i, h in enumerate(tested, start=1):
        h.rank = i

    aliasing = []
    cats = list(categorical)
    for i in range(len(cats)):
        for j in range(i + 1, len(cats)):
            v = cramers_v(df[cats[i]], df[cats[j]])
            if math.isfinite(v) and v > 0.8:
                aliasing.append({"a": cats[i], "b": cats[j], "cramers_v": v})

    return {
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "alpha": alpha,
        "n": n,
        "n_pre": n_pre,
        "n_post": n_post,
        "change_index": change_index,
        "observed_shift_mm": observed,
        "hypotheses": [h.to_dict() for h in tested] + [h.to_dict() for h in hyps if h.status != "tested"],
        "aliasing": aliasing,
    }
