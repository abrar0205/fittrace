"""Scan-line, sub-pixel gap measurement between two panel edges.

Algorithm ``fittrace.gap.scanline-subpixel`` (see docs/methodology.md):

1. Validate the image (2-D, 8/16-bit or float, minimum size, dynamic range,
   saturation).
2. Validate the calibration. Without a valid calibration the algorithm still
   measures in pixels, but returns no millimetre value.
3. Gaussian smoothing (configurable sigma) to suppress sensor noise.
4. For every ``row_step``-th row, take the horizontal intensity derivative and
   find the best *falling* (panel -> gap) and *rising* (gap -> panel) edge pair
   whose interior is darker than its surroundings.
5. Refine each edge to sub-pixel precision with a three-point parabolic fit of
   the derivative peak.
6. Fit a straight line ``x = a*y + b`` to each edge with iterative
   MAD-based outlier rejection.
7. Check that both edges are approximately parallel and enough rows are valid.
8. Gap = horizontal edge distance at the measurement row times ``cos(theta)``
   (perpendicular distance between parallel lines), converted to mm with the
   calibration scale.

The function never invents a value: if prerequisites fail it returns a result
with ``ok=False``, a machine-readable ``failure_code`` and diagnostics.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

ALGORITHM_NAME = "fittrace.gap.scanline-subpixel"
ALGORITHM_VERSION = "1.1.0"  # 1.1: noise-adaptive edge threshold (dark paints)


@dataclass(frozen=True)
class GapParams:
    smoothing_sigma_px: float = 1.5
    row_step: int = 4
    roi_margin_px: int = 6
    min_dynamic_range: float = 40.0  # grey levels between p1 and p99
    min_edge_gradient: float = 2.0  # floor of the edge threshold, grey levels / px after smoothing
    edge_snr: float = 6.0  # edge threshold = max(floor, edge_snr x robust gradient noise)
    min_gap_px: float = 3.0
    min_valid_row_fraction: float = 0.35
    max_parallel_deviation_deg: float = 1.5
    outlier_mad_k: float = 3.5
    max_saturated_fraction: float = 0.05

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EdgeLine:
    slope: float  # dx/dy
    intercept: float  # x at y = 0
    inliers: int
    total: int
    residual_rms_px: float

    def x_at(self, y: float) -> float:
        return self.slope * y + self.intercept

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan(self.slope))


@dataclass
class GapResult:
    ok: bool
    algorithm: str = ALGORITHM_NAME
    version: str = ALGORITHM_VERSION
    params: dict = field(default_factory=dict)
    failure_code: str | None = None
    failure_message: str | None = None
    gap_px: float | None = None
    gap_mm: float | None = None
    mm_per_px: float | None = None
    calibrated: bool = False
    angle_deg: float | None = None
    measurement_row: float | None = None
    row_width_std_px: float | None = None
    std_error_px: float | None = None
    std_error_mm: float | None = None
    valid_rows: int = 0
    sampled_rows: int = 0
    flags: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    overlay: dict = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class _Fail(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _to_gray_float(img: np.ndarray) -> np.ndarray:
    if not isinstance(img, np.ndarray):
        raise _Fail("invalid_input", "image must be a numpy array")
    if img.ndim == 3 and img.shape[2] in (3, 4):
        img = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    if img.ndim != 2:
        raise _Fail("invalid_input", f"expected a 2-D grayscale image, got shape {img.shape}")
    if img.dtype == np.uint8:
        return img.astype(np.float64)
    if img.dtype == np.uint16:
        return img.astype(np.float64) / 257.0
    if np.issubdtype(img.dtype, np.floating):
        if not np.all(np.isfinite(img)):
            raise _Fail("invalid_input", "image contains non-finite values")
        return np.clip(img, 0.0, 1.0) * 255.0
    raise _Fail("invalid_input", f"unsupported dtype {img.dtype}")


def _parabolic_peak(g: np.ndarray, i: int) -> float:
    """Sub-pixel location of an extremum at index i using a 3-point parabola."""
    if i <= 0 or i >= len(g) - 1:
        return float(i)
    y0, y1, y2 = g[i - 1], g[i], g[i + 1]
    denom = y0 - 2.0 * y1 + y2
    if denom == 0:
        return float(i)
    delta = 0.5 * (y0 - y2) / denom
    return float(i + max(-0.5, min(0.5, delta)))


def _row_edges(profile: np.ndarray, grad: np.ndarray, p: GapParams, thr: float) -> tuple[float, float, float] | None:
    """Return (x_left, x_right, pair_strength) for one row, or None."""
    n = len(grad)
    # Local extrema of the derivative exceeding the gradient threshold.
    interior = slice(1, n - 1)
    g_c = grad[interior]
    is_min = (g_c < grad[:-2]) & (g_c <= grad[2:]) & (g_c < -thr)
    is_max = (g_c > grad[:-2]) & (g_c >= grad[2:]) & (g_c > thr)
    falls = np.nonzero(is_min)[0] + 1
    rises = np.nonzero(is_max)[0] + 1
    if len(falls) == 0 or len(rises) == 0:
        return None
    # Keep the strongest few candidates to bound the pair search.
    falls = falls[np.argsort(grad[falls])[:6]]
    rises = rises[np.argsort(-grad[rises])[:6]]
    best = None
    for f in falls:
        for r in rises:
            if r - f < p.min_gap_px:
                continue
            inside = profile[f + 1 : r]
            if inside.size == 0:
                continue
            left_ref = profile[max(0, f - 6) : f].mean() if f > 0 else profile[0]
            right_ref = profile[r + 1 : r + 7].mean() if r + 1 < n else profile[-1]
            if inside.mean() >= min(left_ref, right_ref):
                continue  # interior must be darker than both panels (shadowed gap)
            strength = -grad[f] + grad[r]
            if best is None or strength > best[2]:
                best = (f, r, strength)
    if best is None:
        return None
    f, r, strength = best
    return _parabolic_peak(grad, int(f)), _parabolic_peak(grad, int(r)), float(strength)


def _robust_line(ys: np.ndarray, xs: np.ndarray, k: float) -> tuple[EdgeLine, np.ndarray]:
    mask = np.ones(len(ys), dtype=bool)
    slope, intercept = 0.0, float(np.median(xs))
    for _ in range(5):
        if mask.sum() < 3:
            break
        A = np.vstack([ys[mask], np.ones(mask.sum())]).T
        slope, intercept = np.linalg.lstsq(A, xs[mask], rcond=None)[0]
        res = xs - (slope * ys + intercept)
        mad = np.median(np.abs(res[mask] - np.median(res[mask])))
        scale = max(1.4826 * mad, 0.05)
        new_mask = np.abs(res) <= k * scale
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask
    res = xs - (slope * ys + intercept)
    rms = float(np.sqrt(np.mean(res[mask] ** 2))) if mask.any() else float("nan")
    return EdgeLine(float(slope), float(intercept), int(mask.sum()), len(ys), rms), mask


def measure_gap(
    image: np.ndarray,
    mm_per_px: float | None,
    params: GapParams | None = None,
    measurement_row: float | None = None,
) -> GapResult:
    """Measure the perpendicular gap between two panel edges in ``image``.

    ``mm_per_px`` is the calibration scale; pass ``None`` when no valid
    calibration exists - the result is then pixel-only (``calibrated=False``).
    ``measurement_row`` defaults to the image centre row.
    """
    p = params or GapParams()
    t0 = time.perf_counter()
    result = GapResult(ok=False, params=p.to_dict())
    try:
        gray = _to_gray_float(image)
        h, w = gray.shape
        result.diagnostics["image_shape"] = [int(h), int(w)]
        if h < 32 or w < 32:
            raise _Fail("image_too_small", f"image {w}x{h} is below the 32x32 minimum")

        p1, p99 = np.percentile(gray, [1, 99])
        dyn = float(p99 - p1)
        sat = float(np.mean(gray >= 254.5))
        result.diagnostics.update(dynamic_range=round(dyn, 2), saturated_fraction=round(sat, 5))
        if dyn < p.min_dynamic_range:
            raise _Fail("low_contrast", f"dynamic range {dyn:.1f} below {p.min_dynamic_range}")
        if sat > p.max_saturated_fraction:
            result.flags.append("saturation")

        calibrated = mm_per_px is not None and math.isfinite(mm_per_px) and mm_per_px > 0
        if mm_per_px is not None and not calibrated:
            raise _Fail("invalid_calibration", f"calibration scale {mm_per_px!r} is not a positive number")
        if not calibrated:
            result.flags.append("uncalibrated")

        sm = cv2.GaussianBlur(gray, (0, 0), p.smoothing_sigma_px) if p.smoothing_sigma_px > 0 else gray
        grad = cv2.Sobel(sm, cv2.CV_64F, 1, 0, ksize=3) / 8.0  # grey levels per pixel

        # Noise estimate from the residual of the smoothing (robust, MAD based).
        hp = gray - cv2.GaussianBlur(gray, (0, 0), 2.0)
        noise = float(1.4826 * np.median(np.abs(hp - np.median(hp))))
        result.diagnostics["noise_estimate_grey"] = round(noise, 3)

        m = p.roi_margin_px
        # Noise-adaptive edge threshold: robust (MAD) spread of the horizontal gradient, which
        # is dominated by flat panel and gap areas. Dark paints have low contrast but also
        # low gradient noise, so a fixed threshold either misses their edges or admits noise.
        g_roi = grad[m : h - m, m : w - m]
        sigma_g = float(1.4826 * np.median(np.abs(g_roi - np.median(g_roi))))
        thr = max(p.min_edge_gradient, p.edge_snr * sigma_g)
        result.diagnostics.update(gradient_noise=round(sigma_g, 4), edge_threshold=round(thr, 3))
        rows = np.arange(m, h - m, max(1, p.row_step))
        result.sampled_rows = int(len(rows))
        ys, xl, xr, strengths = [], [], [], []
        for y in rows:
            e = _row_edges(sm[y, m : w - m], grad[y, m : w - m], p, thr)
            if e is None:
                continue
            ys.append(float(y))
            xl.append(e[0] + m)
            xr.append(e[1] + m)
            strengths.append(e[2])
        ys_a, xl_a, xr_a = np.array(ys), np.array(xl), np.array(xr)
        result.diagnostics["rows_with_edges"] = len(ys)
        if len(ys) < 3:
            raise _Fail("edges_not_found", f"edge pair found in {len(ys)}/{len(rows)} sampled rows")

        left, lmask = _robust_line(ys_a, xl_a, p.outlier_mad_k)
        right, rmask = _robust_line(ys_a, xr_a, p.outlier_mad_k)
        valid = lmask & rmask
        result.valid_rows = int(valid.sum())
        frac = result.valid_rows / max(1, len(rows))
        result.diagnostics.update(
            valid_row_fraction=round(frac, 3),
            left_edge={"angle_deg": round(left.angle_deg, 4), "inliers": left.inliers, "rms_px": round(left.residual_rms_px, 4)},
            right_edge={"angle_deg": round(right.angle_deg, 4), "inliers": right.inliers, "rms_px": round(right.residual_rms_px, 4)},
            mean_edge_strength=round(float(np.mean(strengths)), 2),
        )
        # Overlay geometry comes straight from the algorithm state.
        result.overlay = {
            "rows": [
                {"y": round(y, 2), "xl": round(a, 3), "xr": round(b, 3), "inlier": bool(v)}
                for y, a, b, v in zip(ys_a.tolist(), xl_a.tolist(), xr_a.tolist(), valid.tolist(), strict=True)
            ],
            "left_line": [[round(left.x_at(0), 3), 0.0], [round(left.x_at(h - 1), 3), float(h - 1)]],
            "right_line": [[round(right.x_at(0), 3), 0.0], [round(right.x_at(h - 1), 3), float(h - 1)]],
            "roi": [m, m, w - 2 * m, h - 2 * m],
        }

        if frac < p.min_valid_row_fraction:
            result.flags.append("partial_visibility")
            raise _Fail(
                "insufficient_valid_rows",
                f"only {result.valid_rows}/{len(rows)} rows ({frac:.0%}) produced consistent edges",
            )
        if frac < 0.9:
            result.flags.append("partial_visibility")

        dpar = abs(left.angle_deg - right.angle_deg)
        result.diagnostics["parallel_deviation_deg"] = round(dpar, 4)
        if dpar > p.max_parallel_deviation_deg:
            raise _Fail("edges_not_parallel", f"edge angles differ by {dpar:.2f} deg")

        theta = math.atan(0.5 * (left.slope + right.slope))
        valid_y = ys_a[valid]
        y0 = float(measurement_row) if measurement_row is not None else (h - 1) / 2.0
        if y0 < valid_y.min() or y0 > valid_y.max():
            result.flags.append("measurement_row_extrapolated")
        ct = math.cos(theta)
        gap_px = (right.x_at(y0) - left.x_at(y0)) * ct
        if gap_px < p.min_gap_px:
            raise _Fail("gap_below_resolution", f"gap {gap_px:.2f}px below minimum {p.min_gap_px}px")

        widths = (xr_a[valid] - xl_a[valid]) * ct
        wstd = float(np.std(widths, ddof=1)) if len(widths) > 1 else float("nan")
        se = wstd / math.sqrt(len(widths)) if len(widths) > 1 else float("nan")

        result.ok = True
        result.gap_px = float(gap_px)
        result.angle_deg = math.degrees(theta)
        result.measurement_row = y0
        result.row_width_std_px = wstd
        result.std_error_px = se
        result.calibrated = calibrated
        if calibrated:
            result.mm_per_px = float(mm_per_px)  # type: ignore[arg-type]
            result.gap_mm = float(gap_px * mm_per_px)  # type: ignore[operator]
            result.std_error_mm = float(se * mm_per_px)  # type: ignore[operator]
        # Measurement segment: perpendicular from the left line at y0 to the right line.
        xl0 = left.x_at(y0)
        nx, ny = math.cos(theta), -math.sin(theta)
        result.overlay["measurement"] = {
            "p1": [round(xl0, 3), round(y0, 3)],
            "p2": [round(xl0 + gap_px * nx, 3), round(y0 + gap_px * ny, 3)],
        }
    except _Fail as f:
        result.ok = False
        result.failure_code = f.code
        result.failure_message = f.message
    finally:
        result.duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return result
