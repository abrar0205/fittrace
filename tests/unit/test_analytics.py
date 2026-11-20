import numpy as np
import pandas as pd
import pytest

from fittrace.analytics.changepoint import cusum, mean_shift
from fittrace.analytics.contributors import benjamini_hochberg, rank_contributors
from fittrace.analytics.investigation import investigate
from fittrace.analytics.spc import imr_chart
from fittrace.evaluation.investigation_bench import run_investigation_benchmark
from fittrace.simulation.factory import Fault, SimConfig, simulate


def test_imr_limits_match_textbook_formula():
    rng = np.random.default_rng(0)
    x = rng.normal(10, 1, 200)
    ch = imr_chart(x, baseline_n=50)
    base = x[:50]
    mr = np.abs(np.diff(base)).mean()
    assert ch["center"] == pytest.approx(base.mean())
    assert ch["ucl"] == pytest.approx(base.mean() + 3 * mr / 1.128)
    assert ch["mr_ucl"] == pytest.approx(3.267 * mr)


def test_imr_detects_injected_shift_and_warns_on_small_baseline():
    rng = np.random.default_rng(1)
    x = np.r_[rng.normal(0, 1, 100), rng.normal(2.0, 1, 50)]
    ch = imr_chart(x, baseline_n=100)
    assert ch["first_signal_index"] is not None and ch["first_signal_index"] >= 100
    assert any("at least 20" in w for w in imr_chart(x[:15], baseline_n=15)["warnings"])


def test_mean_shift_localises_change():
    rng = np.random.default_rng(2)
    x = np.r_[rng.normal(0, 0.1, 150), rng.normal(0.15, 0.1, 100)]
    r = mean_shift(x, n_perm=499, seed=0)
    assert r["found"] and abs(r["index"] - 150) <= 12 and r["p_value"] < 0.01
    assert r["delta"] == pytest.approx(0.15, abs=0.04)


def test_mean_shift_null_is_not_significant():
    x = np.random.default_rng(3).normal(0, 1, 200)
    assert mean_shift(x, n_perm=499, seed=0)["p_value"] > 0.05


def test_cusum_alarm_after_shift():
    x = np.r_[np.zeros(50), np.full(30, 1.5)]
    r = cusum(x, 0.0, 1.0, k=0.5, h=5.0)
    assert r["alarm_index"] == 55 and r["direction"] == "up"


def test_benjamini_hochberg_known_values():
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.2])
    assert q == pytest.approx([0.04, 0.0533333, 0.0533333, 0.2], rel=1e-4)


def test_contributor_ranking_recovers_categorical_effect():
    rng = np.random.default_rng(4)
    n, k = 300, 150
    f = rng.choice(["A", "B", "C"], n)
    y = rng.normal(0, 0.1, n) + np.where((np.arange(n) >= k) & (f == "B"), 0.4, 0.0)
    df = pd.DataFrame({"y": y, "fixture": f, "noise_param": rng.normal(0, 1, n)})
    r = rank_contributors(df, "y", k, {"fixture": "S20"}, {"noise_param": None})
    top = r["hypotheses"][0]
    assert top["level"] == "B" and top["significant"] and top["rank"] == 1
    assert top["explained_fraction"] == pytest.approx(1.0, abs=0.2)
    assert not any(h["significant"] for h in r["hypotheses"][1:])


def test_investigation_on_simulated_fixture_fault():
    from fittrace.evaluation.investigation_bench import unit_frame

    res = simulate(SimConfig(seed=11, n_units=360, faults=[Fault("fixture_shift", "FX-203", 180, 0.45)]))
    meas = {u.serial: u.true_gaps["FD-FF-M"] for u in res.units}
    out = investigate(unit_frame(res, meas), events=res.equipment_events, n_perm=299)
    assert out["conclusion"] == "shift_detected"
    assert abs(out["change_point"]["index"] - 180) < 15
    assert out["contributors"]["hypotheses"][0]["level"] == "FX-203"
    assert any("not confirmed root causes" in x for x in out["limitations"])


def test_simulation_is_deterministic_and_fault_is_causal():
    cfg = SimConfig(seed=5, n_units=200, faults=[Fault("fixture_shift", "FX-201", 100, 0.5)])
    a, b = simulate(cfg), simulate(cfg)
    assert [u.true_gaps for u in a.units] == [u.true_gaps for u in b.units]
    fixed = simulate(SimConfig(seed=5, n_units=200, faults=cfg.faults, realigned=("FX-201",)))
    for ua, uf in zip(a.units, fixed.units, strict=True):
        s20 = next(s["equipment"] for s in ua.route if s["station"] == "S20")
        diff = ua.true_gaps["FD-FF-M"] - uf.true_gaps["FD-FF-M"]
        expected = 0.5 if (s20 == "FX-201" and ua.index >= 100) else 0.0
        assert diff == pytest.approx(expected, abs=1e-6)


def test_investigation_benchmark_smoke():
    r = run_investigation_benchmark(n_runs=3, n_null=1, n_perm=99, n_units=300)
    assert r["overall"]["faulted_runs"] == 3
    assert 0.0 <= r["overall"]["top1_full_history"] <= 1.0
