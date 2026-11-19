"""Mean-shift change-point localisation and CUSUM detection."""

from __future__ import annotations

import numpy as np


def _shift_stat(x: np.ndarray, min_segment: int) -> tuple[np.ndarray, np.ndarray]:
    """Standardised two-sample mean difference for every split position.

    Returns (positions, |stat|) where position ``k`` means the new segment
    starts at index ``k``. Vectorised over a batch of rows when ``x`` is 2-D.
    """
    x2 = np.atleast_2d(x)
    n = x2.shape[1]
    ks = np.arange(min_segment, n - min_segment + 1)
    cs = np.cumsum(x2, axis=1)
    total = cs[:, -1:]
    left_sum = cs[:, ks - 1]
    m1 = left_sum / ks
    m2 = (total - left_sum) / (n - ks)
    stat = np.abs(m2 - m1) * np.sqrt(ks * (n - ks) / n)
    return ks, stat


def mean_shift(values, min_segment: int = 10, n_perm: int = 999, seed: int = 0) -> dict:
    """Single most likely mean shift with a permutation p-value.

    The statistic is the maximum standardised mean difference over all split
    points (equivalent to the least-squares single change point). The p-value
    compares it with the same maximum under random permutations of the series,
    i.e. under the null hypothesis of exchangeable observations (no shift).
    """
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2 * min_segment:
        return {"found": False, "reason": f"need at least {2 * min_segment} points, have {n}", "n": n}
    ks, stat = _shift_stat(x, min_segment)
    j = int(np.argmax(stat[0]))
    k = int(ks[j])
    obs = float(stat[0, j])
    rng = np.random.default_rng(seed)
    exceed = 0
    batch = 200
    done = 0
    while done < n_perm:
        m = min(batch, n_perm - done)
        perms = np.array([rng.permutation(x) for _ in range(m)])
        _, s = _shift_stat(perms, min_segment)
        exceed += int(np.sum(s.max(axis=1) >= obs))
        done += m
    p = (exceed + 1) / (n_perm + 1)
    before, after = x[:k], x[k:]
    resid = np.concatenate([before - before.mean(), after - after.mean()])
    sigma = float(np.std(resid, ddof=2))
    return {
        "found": True,
        "index": k,
        "mean_before": float(before.mean()),
        "mean_after": float(after.mean()),
        "delta": float(after.mean() - before.mean()),
        "sigma_within": sigma,
        "statistic": obs,
        "p_value": float(p),
        "n_perm": n_perm,
        "n": n,
        "profile": stat[0].tolist(),
        "profile_start": int(ks[0]),
    }


def cusum(values, mu0: float, sigma: float, k: float = 0.5, h: float = 5.0) -> dict:
    """Two-sided tabular CUSUM (Page). ``k`` and ``h`` are in units of sigma."""
    x = (np.asarray(values, dtype=float) - mu0) / sigma
    cp = np.zeros(len(x))
    cn = np.zeros(len(x))
    alarm, direction = None, None
    for i, z in enumerate(x):
        cp[i] = max(0.0, (cp[i - 1] if i else 0.0) + z - k)
        cn[i] = max(0.0, (cn[i - 1] if i else 0.0) - z - k)
        if alarm is None and (cp[i] > h or cn[i] > h):
            alarm, direction = i, ("up" if cp[i] > h else "down")
    return {"alarm_index": alarm, "direction": direction, "c_plus": cp.tolist(), "c_minus": cn.tolist(), "k": k, "h": h}
