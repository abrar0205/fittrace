"""Calibrated synthetic panel-gap images.

The generator renders a top-down view of two adjacent body panels separated by a
gap. Geometry is defined in millimetres and converted to pixels with an explicit
camera scale (``mm_per_px``). Optional edge roll-off models hem shading. Rendering is done by area-sampling a supersampled
grid, followed by an optical blur (Gaussian PSF), illumination non-uniformity and
additive sensor noise, then quantised to 8 bit.

Coordinate model (pixel frame, origin top-left, x to the right, y down)::

    u(x, y) = (x - cx) * cos(theta) - (y - cy) * sin(theta)

``u`` is the signed distance along the gap normal. Pixels with
``|u - offset| < gap/2`` lie inside the gap; ``u`` below that is the left panel,
above it the right panel. ``gap`` is therefore the *perpendicular* distance
between the two (parallel) edges - the quantity an engineer calls the gap.

The ground-truth gap is returned separately in :class:`GroundTruth`. The
measurement algorithm never receives it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

GENERATOR_VERSION = "panel-gap-generator/2.0.0"


@dataclass(frozen=True)
class Calibration:
    """Camera scale for a fronto-parallel view of the panel plane."""

    mm_per_px: float
    reference: str = "CAL-SIM-001"
    method: str = "simulated-reference-target"

    def validate(self) -> None:
        if not np.isfinite(self.mm_per_px) or self.mm_per_px <= 0:
            raise ValueError(f"invalid mm_per_px: {self.mm_per_px!r}")


@dataclass(frozen=True)
class SceneParams:
    """Everything needed to render one inspection image deterministically."""

    gap_mm: float
    mm_per_px: float = 0.025
    width_px: int = 480
    height_px: int = 240
    center_offset_mm: float = 0.0
    angle_deg: float = 0.0
    left_level: float = 0.78
    right_level: float = 0.74
    gap_level: float = 0.07
    edge_blur_px: float = 1.1
    illumination_gradient: float = 0.0
    vignette: float = 0.0
    noise_sigma: float = 0.015
    occlusion_fraction: float = 0.0
    edge_rolloff_mm: float = 0.0
    seed: int = 0
    supersample: int = 4
    # Generator 2.0 appearance (colour camera). ``paint=None`` keeps the greyscale model.
    paint: str | None = None
    gap_style: str = "flange"
    orange_peel: float = 0.0
    crease_y: float = -1.0
    reflection: float = 0.0
    reflection_angle_deg: float = 60.0
    reflection_pos: float = 0.5
    reflection_width_px: float = 40.0
    dust: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GroundTruth:
    """Known geometry used *only* for evaluation."""

    gap_mm: float
    gap_px: float
    angle_deg: float
    left_edge_x_at_center_px: float
    right_edge_x_at_center_px: float
    generator_version: str = GENERATOR_VERSION
    params: dict = field(default_factory=dict)


def _edge_positions(p: SceneParams) -> tuple[float, float, float, float]:
    """Return (cx, cy, left_u, right_u) in pixel units."""
    cx = (p.width_px - 1) / 2.0
    cy = (p.height_px - 1) / 2.0
    gap_px = p.gap_mm / p.mm_per_px
    offset_px = p.center_offset_mm / p.mm_per_px
    return cx, cy, offset_px - gap_px / 2.0, offset_px + gap_px / 2.0


def render_panel_gap(p: SceneParams) -> tuple[np.ndarray, GroundTruth]:
    """Render an 8-bit image and its ground truth.

    Greyscale (H x W) when ``p.paint`` is None, otherwise a colour image in BGR
    channel order (H x W x 3), as OpenCV reads and writes it.
    """
    if p.gap_mm < 0:
        raise ValueError("gap_mm must be non-negative")
    Calibration(p.mm_per_px).validate()
    rng = np.random.default_rng(p.seed)

    s = max(1, int(p.supersample))
    theta = np.deg2rad(p.angle_deg)
    cx, cy, left_u, right_u = _edge_positions(p)

    # Sub-pixel sample centres for area sampling.
    offs = (np.arange(s) + 0.5) / s - 0.5
    ys = (np.arange(p.height_px)[:, None] + offs[None, :]).reshape(-1)
    xs = (np.arange(p.width_px)[:, None] + offs[None, :]).reshape(-1)
    X, Y = np.meshgrid(xs, ys)
    U = (X - cx) * np.cos(theta) - (Y - cy) * np.sin(theta)

    if p.paint is not None:
        return _render_colour(p, U, left_u, right_u, s, rng)

    hi = np.where(U < left_u, p.left_level, np.where(U > right_u, p.right_level, p.gap_level))
    if p.edge_rolloff_mm > 0:
        # Hemmed panel edges curve away from the camera and darken towards the
        # silhouette. Brightness ramps from 35% to 100% of the panel level over
        # ``edge_rolloff_mm`` (sqrt profile). The ground-truth edge stays at the
        # silhouette, so this produces a real, measurable edge-definition bias.
        r = p.edge_rolloff_mm / p.mm_per_px
        for d, level in ((left_u - U, p.left_level), (U - right_u, p.right_level)):
            zone = (d >= 0) & (d < r)
            frac = 0.35 + 0.65 * np.sqrt(np.clip(d[zone] / r, 0, 1))
            hi[zone] = p.gap_level + (level - p.gap_level) * frac
    img = hi.reshape(p.height_px, s, p.width_px, s).mean(axis=(1, 3)).astype(np.float64)

    if p.edge_blur_px > 0:
        img = cv2.GaussianBlur(img, (0, 0), sigmaX=p.edge_blur_px, sigmaY=p.edge_blur_px)

    # Illumination: linear ramp across the field plus optional radial vignette.
    xn = (np.arange(p.width_px) / max(1, p.width_px - 1)) - 0.5
    yn = (np.arange(p.height_px) / max(1, p.height_px - 1)) - 0.5
    gain = 1.0 + p.illumination_gradient * xn[None, :]
    if p.vignette > 0:
        r2 = xn[None, :] ** 2 + yn[:, None] ** 2
        gain = gain * (1.0 - p.vignette * r2 / 0.5)
    img = img * gain

    # Partial visibility: an opaque, textured clip covers the top rows.
    if p.occlusion_fraction > 0:
        rows = int(round(p.occlusion_fraction * p.height_px))
        if rows > 0:
            tex = 0.45 + 0.08 * rng.standard_normal((rows, p.width_px))
            img[:rows, :] = cv2.GaussianBlur(tex, (0, 0), 2.0)

    if p.noise_sigma > 0:
        img = img + rng.normal(0.0, p.noise_sigma, img.shape)

    out = np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8)

    gap_px = p.gap_mm / p.mm_per_px
    # Edge x at the centre row (y = cy): u = (x - cx) cos(theta)  ->  x = cx + u / cos(theta)
    ct = np.cos(theta)
    truth = GroundTruth(
        gap_mm=p.gap_mm,
        gap_px=gap_px,
        angle_deg=p.angle_deg,
        left_edge_x_at_center_px=cx + left_u / ct,
        right_edge_x_at_center_px=cx + right_u / ct,
        params=p.to_dict(),
    )
    return out, truth


def _render_colour(p: SceneParams, U: np.ndarray, left_u: float, right_u: float, s: int,
                   rng: np.random.Generator) -> tuple[np.ndarray, GroundTruth]:
    """Colour path: identical geometry and hem roll-off, appearance from ``appearance``."""
    from fittrace.simulation.appearance import PAINTS, render_color

    if p.paint not in PAINTS:
        raise ValueError(f"unknown paint {p.paint!r}")
    if p.gap_style not in ("flange", "pillar"):
        raise ValueError(f"unknown gap_style {p.gap_style!r}")
    # Panel coverage weighted by the hem roll-off (same profile as the greyscale model).
    wl = (U < left_u).astype(np.float64)
    wr = (U > right_u).astype(np.float64)
    if p.edge_rolloff_mm > 0:
        r = p.edge_rolloff_mm / p.mm_per_px
        for d, wgt in ((left_u - U, wl), (U - right_u, wr)):
            zone = (d >= 0) & (d < r)
            wgt[zone] = 0.35 + 0.65 * np.sqrt(np.clip(d[zone] / r, 0, 1))
    h, w = p.height_px, p.width_px
    cover_l = wl.reshape(h, s, w, s).mean(axis=(1, 3))
    cover_r = wr.reshape(h, s, w, s).mean(axis=(1, 3))
    Uc = U.reshape(h, s, w, s).mean(axis=(1, 3))
    u_rel = (Uc - left_u) / max(1e-6, right_u - left_u)
    rgb = render_color(p, cover_l, cover_r, u_rel, rng)

    if p.occlusion_fraction > 0:
        rows = int(round(p.occlusion_fraction * h))
        if rows > 0:
            clip = cv2.GaussianBlur(0.16 + 0.03 * rng.standard_normal((rows, w)), (0, 0), 2.0)
            rgb[:rows, :, :] = np.clip(clip, 0, 1)[..., None] * np.array([1.0, 1.0, 1.08])

    out = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)[:, :, ::-1].copy()  # RGB -> BGR
    gap_px = p.gap_mm / p.mm_per_px
    theta = np.deg2rad(p.angle_deg)
    cx = (p.width_px - 1) / 2.0
    ct = np.cos(theta)
    truth = GroundTruth(gap_mm=p.gap_mm, gap_px=gap_px, angle_deg=p.angle_deg,
                        left_edge_x_at_center_px=cx + left_u / ct, right_edge_x_at_center_px=cx + right_u / ct,
                        params=p.to_dict())
    return out, truth


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:  # pragma: no cover - OpenCV failure
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("could not decode image bytes")
    return img


def params_fingerprint(p: SceneParams) -> str:
    """Stable hash of render parameters (used for idempotent regeneration)."""
    payload = json.dumps(p.to_dict(), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
