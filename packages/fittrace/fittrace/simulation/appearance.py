"""Paint and appearance model for realistic gap-inspection images (generator 2.0).

The geometry (edge positions, hem roll-off, PSF, calibration) is exactly the
same as the greyscale renderer, so the ground truth keeps its meaning. On top of
it, this module renders what a colour gap camera on a body line sees:

* **Paint** from a production mix, with clear-coat **reflections** of booth
  lights, **orange peel** (low-frequency surface texture) and, for metallic
  paints, **flake** sparkle.
* A **styling crease** (body line) crossing both panels.
* What is visible **inside the gap**: at the door/fender gap the hinge-side
  flange in shadow; at the door/door gap the gloss-black B-pillar trim with a
  reflection streak and the ribbed weather seal.
* A per-paint **exposure recipe** (longer exposure for dark paints, partial so
  highlights do not clip), as gap cameras use. Sensor noise has a read and a shot component.

Every quantity is drawn from the scene parameters, so an image is reproducible
from its stored ``scene``. Ground truth is never passed to the algorithm.
"""

from __future__ import annotations

import cv2
import numpy as np

# Invented paint codes (not any manufacturer's). rgb is the diffuse reflectance.
PAINTS: dict[str, dict] = {
    "P-WH1": {"name": "Arctic white", "rgb": (0.86, 0.86, 0.84), "metallic": 0.0, "gloss": 0.55},
    "P-BK1": {"name": "Onyx black", "rgb": (0.040, 0.042, 0.048), "metallic": 0.0, "gloss": 1.0},
    "P-GY1": {"name": "Slate grey", "rgb": (0.22, 0.235, 0.25), "metallic": 0.0, "gloss": 0.8},
    "P-BL3M": {"name": "Cobalt blue metallic", "rgb": (0.05, 0.14, 0.36), "metallic": 1.0, "gloss": 0.9},
    "P-RD1": {"name": "Signal red", "rgb": (0.58, 0.05, 0.06), "metallic": 0.0, "gloss": 0.8},
    "P-SL2M": {"name": "Quartz silver metallic", "rgb": (0.60, 0.62, 0.64), "metallic": 1.0, "gloss": 0.6},
    "P-GR2M": {"name": "Graphite metallic", "rgb": (0.15, 0.155, 0.165), "metallic": 1.0, "gloss": 0.85},
}
# Production mix (share of units).
PAINT_MIX: dict[str, float] = {"P-WH1": 0.28, "P-BK1": 0.20, "P-GY1": 0.14, "P-BL3M": 0.12, "P-RD1": 0.11,
                               "P-SL2M": 0.09, "P-GR2M": 0.06}
GAP_STYLES = ("flange", "pillar")


def luma(rgb) -> float:
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def exposure_for(paint: str) -> float:
    """Exposure recipe: lengthen exposure for dark paints, but only partly (square root
    of the full correction), and never so far that the strongest colour channel of the
    paint would sit above 0.88 of full scale. Without that cap a saturated red was
    pushed past the sensor limit in its red channel and rendered as a flat, clipped slab."""
    rgb = PAINTS[paint]["rgb"]
    return float(min(np.clip(np.sqrt(0.60 / luma(rgb)), 0.8, 4.0), 0.88 / max(rgb)))


def _smooth_noise(rng: np.random.Generator, shape: tuple[int, int], sigma: float) -> np.ndarray:
    n = cv2.GaussianBlur(rng.standard_normal(shape), (0, 0), sigma)
    return n / max(1e-9, float(n.std()))


def render_color(p, cover_left: np.ndarray, cover_right: np.ndarray, u_rel: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
    """Return an RGB float image in [0, 1] (before quantisation).

    ``cover_left`` / ``cover_right``: per-pixel area coverage of each panel,
    already weighted by the hem roll-off (the same field the greyscale renderer
    uses). ``u_rel``: position across the gap (0 at the left edge, 1 at the right).
    """
    h, w = cover_left.shape
    paint = PAINTS[p.paint]
    base = np.array(paint["rgb"], dtype=np.float64)
    L = luma(base)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)

    # ---- panel radiance (diffuse paint x texture), per panel
    tex = 1.0 + p.orange_peel * _smooth_noise(rng, (h, w), 4.0)
    if p.crease_y >= 0:  # styling crease: lit upper flank, shaded lower flank
        dy = (yy - p.crease_y * h) / 5.0
        tex = tex * (1.0 - 0.32 * dy * np.exp(-0.5 * dy * dy))
    k_left, k_right = p.left_level / 0.77, p.right_level / 0.77  # panels face the light slightly differently
    panel_l = base[None, None, :] * (tex * k_left)[..., None]
    panel_r = base[None, None, :] * (tex * k_right)[..., None]

    # ---- gap radiance: what is behind the gap, darker than any panel edge
    g = (0.06 * L + 0.002) * (0.75 + 0.5 * (yy / max(1, h - 1)))  # light falls off down the gap
    gap = np.repeat(g[..., None], 3, axis=2)
    if p.gap_style == "flange":
        band = np.clip(1 - np.abs(u_rel - 0.68) / 0.13, 0, 1) ** 0.7  # hinge-side flange, painted, in shadow
        gap = gap + band[..., None] * base[None, None, :] * 0.16
    else:
        streak = np.exp(-0.5 * ((u_rel - 0.32) / 0.045) ** 2)  # gloss-black B-pillar trim reflection
        gap = gap + streak[..., None] * (0.20 * L + 0.004)
        seal = np.clip((u_rel - 0.74) / 0.06, 0, 1) * (u_rel <= 1.0)  # ribbed weather seal
        ribs = 0.5 + 0.5 * np.sin(yy * 2 * np.pi / 6.0)
        gap = gap + (seal * (0.05 * L + 0.002) * ribs)[..., None]

    cov_gap = np.clip(1.0 - cover_left - cover_right, 0.0, 1.0)
    img = gap * cov_gap[..., None] + panel_l * cover_left[..., None] + panel_r * cover_right[..., None]

    # ---- metallic flake: sub-pixel sparkles on fully visible panel
    on_panel = (cover_left + cover_right) > 0.999
    if paint["metallic"] > 0:
        sparkle = (rng.random((h, w)) < 0.025) * rng.uniform(0.15, 0.6, (h, w)) * on_panel
        img = img + (sparkle * L * 1.4)[..., None]

    # ---- dust specks
    for _ in range(int(p.dust)):
        cxs, cys = rng.uniform(0, w), rng.uniform(0, h)
        mask = ((xx - cxs) ** 2 + (yy - cys) ** 2) < rng.uniform(0.8, 2.5) ** 2
        img[mask & on_panel] *= 0.55

    # ---- optics: PSF blur, exposure recipe, lighting falloff
    img = cv2.GaussianBlur(img, (0, 0), p.edge_blur_px) if p.edge_blur_px > 0 else img
    img = img * exposure_for(p.paint)
    xn = xx / max(1, w - 1) - 0.5
    yn = yy / max(1, h - 1) - 0.5
    img = img * (1.0 + p.illumination_gradient * xn - p.vignette * (xn * xn + yn * yn) / 0.5)[..., None]

    # ---- clear-coat reflection of a booth light tube (neutral, on the panels only)
    if p.reflection > 0:
        a = np.deg2rad(p.reflection_angle_deg)
        d = (xx - p.reflection_pos * w) * np.cos(a) + (yy - h / 2) * np.sin(a)
        band = np.exp(-0.5 * (d / p.reflection_width_px) ** 2) * paint["gloss"] * p.reflection
        img = img + (band * 0.42 * (cover_left + cover_right))[..., None]

    # ---- sensor: read noise + shot noise, per channel
    sigma = np.sqrt(p.noise_sigma**2 + 0.00012 * np.clip(img, 0, None))
    img = img + rng.standard_normal(img.shape) * sigma
    return np.clip(img, 0.0, 1.0)
