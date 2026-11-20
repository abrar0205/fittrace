"""Investigation orchestration: change point -> contributors -> limitations.

Input is a production-ordered table that ends at the triggering inspection, so
an investigation only uses information available at that moment.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from fittrace.analytics.changepoint import cusum, mean_shift
from fittrace.analytics.contributors import rank_contributors

CATEGORICAL = {"s10_fixture": "S10", "s20_fixture": "S20", "s30_tool": "S30", "s40_booth": "S40", "paint": None,
               "batch": None, "shift": None}
CONTINUOUS = {"clamp_pressure_bar": "S10", "weld_current_ka": "S20", "ambient_temp_c": "S20", "hinge_torque_nm": "S30",
              "film_build_um": "S40", "booth_temp_c": "S40"}


def shift_label(ts: pd.Timestamp) -> str:
    h = ts.hour
    return "A (06-14)" if 6 <= h < 14 else ("B (14-22)" if 14 <= h < 22 else "C (22-06)")


def investigate(
    df: pd.DataFrame,
    target: str = "deviation_mm",
    events: list[dict] | None = None,
    baseline_n: int = 60,
    alpha: float = 0.05,
    n_perm: int = 999,
    seed: int = 0,
    event_window_h: tuple[float, float] = (12.0, 2.0),
) -> dict:
    df = df.reset_index(drop=True)
    y = df[target].to_numpy(dtype=float)
    result: dict = {"n_units": int(len(df)), "target": target, "limitations": []}
    cp = mean_shift(y, min_segment=max(8, min(20, len(y) // 10)), n_perm=n_perm, seed=seed)
    result["change_point"] = {k: v for k, v in cp.items() if k != "profile"}
    result["change_profile"] = {"start": cp.get("profile_start"), "values": cp.get("profile")}
    b = min(baseline_n, len(y))
    base = y[:b]
    if len(base) >= 10:
        sig = float(pd.Series(base).diff().abs().mean() / 1.128)
        cs = cusum(y, float(base.mean()), sig)
        result["cusum"] = {"alarm_index": cs["alarm_index"], "direction": cs["direction"], "k": cs["k"], "h": cs["h"],
                           "mu0": float(base.mean()), "sigma": sig}
    if not cp.get("found") or cp["p_value"] >= alpha:
        result["conclusion"] = "no_sustained_shift"
        result["contributors"] = None
        result["limitations"].append(
            "No statistically significant sustained mean shift was found before the trigger; "
            "the deviation may be an isolated event. Contributor ranking was not performed."
        )
        return result

    k = int(cp["index"])
    result["change_point"]["serial"] = str(df.loc[k, "serial"])
    result["change_point"]["built_at"] = pd.Timestamp(df.loc[k, "built_at"]).isoformat()
    cats = {c: s for c, s in CATEGORICAL.items() if c in df.columns}
    conts = {c: s for c, s in CONTINUOUS.items() if c in df.columns}
    contrib = rank_contributors(df, target, k, cats, conts, alpha=alpha)
    if events:
        t_cp = pd.Timestamp(df.loc[k, "built_at"])
        lo, hi = t_cp - timedelta(hours=event_window_h[0]), t_cp + timedelta(hours=event_window_h[1])
        for h in contrib["hypotheses"]:
            if h["factor_type"] != "equipment":
                continue
            near = [
                {**e, "occurred_at": pd.Timestamp(e["occurred_at"]).isoformat(),
                 "hours_before_change": round((t_cp - pd.Timestamp(e["occurred_at"])).total_seconds() / 3600, 2)}
                for e in events
                if e["equipment"] == h["level"] and lo <= pd.Timestamp(e["occurred_at"]) <= hi
            ]
            h["evidence"]["equipment_events_near_change"] = near
    result["contributors"] = contrib
    result["conclusion"] = "shift_detected"
    lim = result["limitations"]
    lim.append("Rankings are statistical associations in observational data, not confirmed root causes.")
    lim.append(
        f"The change point is estimated from {len(df)} units up to the trigger; "
        f"{contrib['n_post']} units are in the shifted regime. Small post-change samples widen uncertainty."
    )
    if contrib["aliasing"]:
        pairs = ", ".join(f"{a['a']}~{a['b']} (V={a['cramers_v']:.2f})" for a in contrib["aliasing"])
        lim.append(f"Factors are strongly associated with each other and cannot be separated: {pairs}.")
    ne = [h for h in contrib["hypotheses"] if h["status"] == "not_estimable"]
    if ne:
        lim.append(f"{len(ne)} candidate levels were not estimable (e.g. material batches that exist only after the change).")
    lim.append(
        "Equipment events near the change point are shown as context and do not affect the ranking, "
        "because routine events exist for every resource."
    )
    lim.append("Only recorded factors can be ranked; an unrecorded cause will not appear in this list.")
    return result
