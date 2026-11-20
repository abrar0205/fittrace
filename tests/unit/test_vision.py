import numpy as np
import pytest

from fittrace.simulation.geometry import SceneParams, decode_image, encode_png, render_panel_gap
from fittrace.vision.gap import GapParams, measure_gap
from fittrace.vision.tolerance import ToleranceSpec, ToleranceStatus


def render(**kw):
    return render_panel_gap(SceneParams(**{"gap_mm": 4.0, "seed": 3, **kw}))


def test_generator_is_deterministic():
    a, _ = render()
    b, _ = render()
    assert np.array_equal(a, b)
    c, _ = render(seed=4)
    assert not np.array_equal(a, c)


def test_generator_ground_truth_geometry():
    img, gt = render(gap_mm=4.0, mm_per_px=0.025, angle_deg=0.0, center_offset_mm=0.0)
    assert gt.gap_px == pytest.approx(160.0)
    assert gt.right_edge_x_at_center_px - gt.left_edge_x_at_center_px == pytest.approx(160.0)
    assert img.dtype == np.uint8 and img.shape == (240, 480)


def test_png_roundtrip_lossless():
    img, _ = render()
    assert np.array_equal(decode_image(encode_png(img)), img)


@pytest.mark.parametrize("gap", [1.0, 3.2, 4.0, 5.7])
@pytest.mark.parametrize("angle", [0.0, 2.5, -4.0])
def test_known_gap_is_recovered_on_ideal_edges(gap, angle):
    img, gt = render(gap_mm=gap, angle_deg=angle, edge_rolloff_mm=0.0, noise_sigma=0.01)
    r = measure_gap(img, 0.025)
    assert r.ok, r.failure_message
    assert abs(r.gap_mm - gt.gap_mm) < 0.003  # 3 um on ideal step edges
    assert r.angle_deg == pytest.approx(angle, abs=0.15)


def test_edge_rolloff_produces_documented_positive_bias():
    img, gt = render(edge_rolloff_mm=0.06)
    r = measure_gap(img, 0.025)
    assert r.ok
    bias_um = (r.gap_mm - gt.gap_mm) * 1000
    assert 10 < bias_um < 40


def test_uncalibrated_measurement_reports_pixels_only():
    img, gt = render()
    r = measure_gap(img, None)
    assert r.ok and r.gap_mm is None and not r.calibrated
    assert "uncalibrated" in r.flags
    assert r.gap_px == pytest.approx(gt.gap_px, abs=2.0)


@pytest.mark.parametrize("bad", [0.0, -0.02, float("nan")])
def test_invalid_calibration_is_rejected(bad):
    img, _ = render()
    r = measure_gap(img, bad)
    assert not r.ok and r.failure_code == "invalid_calibration" and r.gap_mm is None and r.gap_px is None


def test_blank_image_fails_without_fabricated_value():
    r = measure_gap(np.full((240, 480), 128, np.uint8), 0.025)
    assert not r.ok and r.failure_code == "low_contrast"
    assert r.gap_mm is None and r.gap_px is None and r.overlay == {}


def test_invalid_input_shapes():
    assert measure_gap(np.zeros((10, 10, 10, 2)), 0.025).failure_code == "invalid_input"
    assert measure_gap(np.zeros((8, 8), np.uint8), 0.025).failure_code == "image_too_small"
    assert measure_gap("not an image", 0.025).failure_code == "invalid_input"  # type: ignore[arg-type]


def test_heavy_occlusion_refuses_to_measure():
    img, _ = render(occlusion_fraction=0.8)
    r = measure_gap(img, 0.025)
    assert not r.ok and r.failure_code == "insufficient_valid_rows"
    assert r.gap_mm is None and "partial_visibility" in r.flags


def test_partial_occlusion_still_measures_and_flags():
    img, gt = render(occlusion_fraction=0.3, edge_rolloff_mm=0.0)
    r = measure_gap(img, 0.025)
    assert r.ok and "partial_visibility" in r.flags
    assert abs(r.gap_mm - gt.gap_mm) < 0.005


def test_noise_degrades_gracefully():
    errs = []
    for s in range(10):
        img, gt = render(noise_sigma=0.1, seed=s, edge_rolloff_mm=0.0)
        r = measure_gap(img, 0.025)
        assert r.ok
        errs.append(r.gap_mm - gt.gap_mm)
    assert np.sqrt(np.mean(np.square(errs))) < 0.01


def test_overlay_comes_from_algorithm_state():
    img, _ = render()
    r = measure_gap(img, 0.025, GapParams(row_step=8))
    assert len(r.overlay["rows"]) == r.diagnostics["rows_with_edges"]
    p1, p2 = r.overlay["measurement"]["p1"], r.overlay["measurement"]["p2"]
    assert np.hypot(p2[0] - p1[0], p2[1] - p1[1]) == pytest.approx(r.gap_px, rel=1e-3)


def test_tolerance_evaluation_boundaries():
    spec = ToleranceSpec(4.0, -0.5, 0.5)
    assert spec.evaluate(4.5)[0] == ToleranceStatus.IN_TOLERANCE
    assert spec.evaluate(4.5001)[0] == ToleranceStatus.OUT_HIGH
    assert spec.evaluate(3.4999)[0] == ToleranceStatus.OUT_LOW
    assert spec.evaluate(None) == (ToleranceStatus.NOT_EVALUABLE, None)
    with pytest.raises(ValueError):
        ToleranceSpec(4.0, 0.2, 0.5)


# ---- generator 2.0 (colour) and algorithm 1.1 ------------------------------------------

from fittrace.simulation.appearance import PAINTS  # noqa: E402


def colour(**kw):
    base = {"gap_mm": 4.2, "seed": 11, "paint": "P-WH1", "gap_style": "flange", "orange_peel": 0.03, "crease_y": 0.25,
            "reflection": 0.6, "reflection_angle_deg": 50, "reflection_pos": 0.4, "edge_rolloff_mm": 0.06, "dust": 2}
    return render_panel_gap(SceneParams(**{**base, **kw}))


def test_colour_render_is_bgr_and_deterministic():
    a, gt = colour()
    b, _ = colour()
    assert a.shape == (240, 480, 3) and a.dtype == np.uint8 and np.array_equal(a, b)
    assert gt.gap_px == pytest.approx(168.0)
    red, _ = colour(paint="P-RD1")
    assert red[:, :60, 2].mean() > 2 * red[:, :60, 0].mean()  # BGR order: red channel dominates


@pytest.mark.parametrize("paint", list(PAINTS))
@pytest.mark.parametrize("style", ["flange", "pillar"])
def test_every_paint_and_gap_style_is_measured(paint, style):
    img, gt = colour(paint=paint, gap_style=style, reflection=0.0)  # no reflection: hardest case for dark paints
    r = measure_gap(img, 0.025)
    assert r.ok, (paint, style, r.failure_code, r.diagnostics)
    assert 0.010 < r.gap_mm - gt.gap_mm < 0.035  # documented hem-shading bias band


def test_threshold_adapts_to_noise():
    quiet, _ = colour(paint="P-BK1", reflection=0.0, noise_sigma=0.004)
    noisy, _ = colour(paint="P-BK1", reflection=0.0, noise_sigma=0.05)
    tq = measure_gap(quiet, 0.025).diagnostics["edge_threshold"]
    tn = measure_gap(noisy, 0.025).diagnostics["edge_threshold"]
    assert tn > tq


def test_unknown_paint_rejected():
    with pytest.raises(ValueError):
        colour(paint="P-XX9")
