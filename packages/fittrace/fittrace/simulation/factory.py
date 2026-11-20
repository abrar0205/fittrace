"""Simulated body-in-white production, paint shop and end-of-line gap inspection.

This is a *simulation*. It exists so that the investigation workflow can be
tested against a cause that is known by construction. No column is random
noise pretending to be a cause: every process variable either enters the gap
model below with a documented coefficient, or is documented as a distractor
with zero effect.

Plant (one line, ``BIW-1``)::

    S10 Underbody framing   fixtures FX-101, FX-102     clamp_pressure_bar (distractor)
    S20 Side-aperture framing fixtures FX-201..FX-203   weld_current_ka (distractor), ambient_temp_c
    S30 Door hang           nutrunners NR-301, NR-302    hinge_torque_nm
    S40 Paint shop          booths PB-401, PB-402        film_build_um, booth_temp_c (distractor); paint code
    S50 End-of-line gap inspection  colour camera CAM-501 (calibrated, mm_per_px)

Gap model for unit ``u`` at location ``l`` (millimetres)::

    gap = nominal_l
        + s_l * fixture_offset[f20(u)](t)          side-aperture lateral offset
        + s_l * fixture_offset[f10(u)](t) * 0.4    underbody offset (weaker coupling)
        + k_l * (torque_actual(u) - 24.0)           hinge torque effect
        + c_l * (ambient_temp(u) - 21.0)            thermal effect
        + static_bias[f20(u)]                       small static fixture signature
        - 0.002 * (film_build_um(u) - 110)          paint film on both edges narrows the gap
        + eps,   eps ~ N(0, sigma_l)

Paint, booth, film build and image appearance are drawn from a separate random
stream per unit, so adding them did not change the production sequence, the
true faults or any other draw of the base model.

``s_l`` is +1.0 for the front-door/fender gap and -0.6 for the front/rear door
gap: a lateral shift of the side aperture opens one gap and closes the other.

Faults (ground truth, stored separately from production data):

* ``fixture_shift``  - ``fixture_offset[target] += magnitude`` for ``t >= start``.
* ``tool_drift``     - actual torque of ``target`` drifts by ``-magnitude`` N·m
  per 100 units after ``start``; the *reported* torque stays nominal (a
  calibration drift the sensor cannot see).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from fittrace.simulation.appearance import PAINT_MIX

SIMULATOR_VERSION = "biw-gap-simulator/1.0.0"

LINE = {"code": "BIW-1", "name": "Body-in-white line 1"}
STATIONS = [
    {"code": "S10", "name": "Underbody framing", "sequence": 10},
    {"code": "S20", "name": "Side-aperture framing", "sequence": 20},
    {"code": "S30", "name": "Door hang", "sequence": 30},
    {"code": "S40", "name": "Paint shop", "sequence": 40},
    {"code": "S50", "name": "End-of-line gap inspection", "sequence": 50},
]
EQUIPMENT = [
    {"code": "FX-101", "station": "S10", "kind": "fixture", "name": "Underbody geo fixture A"},
    {"code": "FX-102", "station": "S10", "kind": "fixture", "name": "Underbody geo fixture B"},
    {"code": "FX-201", "station": "S20", "kind": "fixture", "name": "Side-aperture fixture 1"},
    {"code": "FX-202", "station": "S20", "kind": "fixture", "name": "Side-aperture fixture 2"},
    {"code": "FX-203", "station": "S20", "kind": "fixture", "name": "Side-aperture fixture 3"},
    {"code": "NR-301", "station": "S30", "kind": "tool", "name": "Hinge nutrunner 1"},
    {"code": "NR-302", "station": "S30", "kind": "tool", "name": "Hinge nutrunner 2"},
    {"code": "PB-401", "station": "S40", "kind": "booth", "name": "Paint booth line 1"},
    {"code": "PB-402", "station": "S40", "kind": "booth", "name": "Paint booth line 2"},
    {"code": "CAM-501", "station": "S50", "kind": "camera", "name": "Colour gap camera, LH doors"},
]
LOCATIONS = [
    {
        "code": "FD-FF-M",
        "name": "Front door to front fender, mid",
        "description": "Gap between LH front door leading edge and front fender, at belt-line height.",
        "nominal_mm": 4.0,
        "lower_tol_mm": -0.5,
        "upper_tol_mm": 0.5,
        "shift_sensitivity": 1.0,
        "torque_coeff": -0.03,
        "temp_coeff": 0.006,
        "sigma": 0.10,
    },
    {
        "code": "FD-RD-M",
        "name": "Front door to rear door, mid",
        "description": "Gap between LH front door trailing edge and rear door, at belt-line height.",
        "nominal_mm": 4.5,
        "lower_tol_mm": -0.5,
        "upper_tol_mm": 0.5,
        "shift_sensitivity": -0.6,
        "torque_coeff": 0.02,
        "temp_coeff": 0.004,
        "sigma": 0.09,
    },
]
FILM_NOMINAL_UM = 110.0
FILM_COEFF_MM_PER_UM = -0.002
GAP_STYLE = {"FD-FF-M": "flange", "FD-RD-M": "pillar"}
CREASE_Y = {"FD-FF-M": 0.22, "FD-RD-M": 0.24}
STATIC_FIXTURE_BIAS = {"FX-201": 0.02, "FX-202": -0.015, "FX-203": 0.0}
TORQUE_NOMINAL = 24.0
TEMP_REF = 21.0
MM_PER_PX = 0.025


@dataclass(frozen=True)
class Fault:
    kind: str  # "fixture_shift" | "tool_drift"
    target: str  # equipment code
    start_index: int  # first affected unit (production order)
    magnitude: float  # mm for fixture_shift, N·m per 100 units for tool_drift
    with_event: bool = True  # log a plausible equipment event at fault start
    description: str = ""


@dataclass
class SimConfig:
    seed: int = 20260214
    n_units: int = 480
    start: datetime = field(default_factory=lambda: datetime(2026, 2, 9, 6, 0, tzinfo=UTC))
    takt_s: float = 210.0
    batch_size: int = 40
    faults: list[Fault] = field(default_factory=list)
    realigned: tuple[str, ...] = ()  # equipment whose faults are corrected (corrective action)
    serial_prefix: str = "SIM"
    serial_offset: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        return d


def default_fault(n_units: int) -> Fault:
    return Fault(
        kind="fixture_shift",
        target="FX-202",
        start_index=int(n_units * 0.55),
        magnitude=0.42,
        with_event=True,
        description="Locator pin replaced on FX-202; lateral datum shifted +0.42 mm (simulated).",
    )


@dataclass
class SimUnit:
    index: int
    serial: str
    built_at: datetime
    batch: str
    route: list[dict]  # per station: station, equipment, started_at, ended_at, params
    true_gaps: dict[str, float]  # location -> mm (ground truth)
    scene: dict[str, dict]  # location -> render nuisance parameters
    torque_actual: float
    paint: str = "P-WH1"


@dataclass
class SimResult:
    config: SimConfig
    units: list[SimUnit]
    equipment_events: list[dict]
    simulator_version: str = SIMULATOR_VERSION


def _fixture_offset(code: str, idx: int, cfg: SimConfig) -> float:
    off = 0.0
    for f in cfg.faults:
        if f.kind == "fixture_shift" and f.target == code and idx >= f.start_index and code not in cfg.realigned:
            off += f.magnitude
    return off


def _torque_drift(code: str, idx: int, cfg: SimConfig) -> float:
    d = 0.0
    for f in cfg.faults:
        if f.kind == "tool_drift" and f.target == code and idx >= f.start_index and code not in cfg.realigned:
            d -= f.magnitude * (idx - f.start_index) / 100.0
    return d


def simulate(cfg: SimConfig) -> SimResult:
    """Run the simulation. Fully deterministic given ``cfg``."""
    rng = np.random.default_rng(cfg.seed)
    units: list[SimUnit] = []
    t = cfg.start
    # Each station routes a unit to one of its parallel resources. Assignment is
    # randomised (not round-robin) so that fixtures at different stations are
    # not aliased with each other.
    s10 = ["FX-101", "FX-102"]
    s20 = ["FX-201", "FX-202", "FX-203"]
    s30 = ["NR-301", "NR-302"]
    for i in range(cfg.n_units):
        gidx = cfg.serial_offset + i
        t = t + timedelta(seconds=float(cfg.takt_s * rng.uniform(0.85, 1.25)))
        # Shift breaks: skip 30 min every 8 h of production.
        if i > 0 and i % int(8 * 3600 / cfg.takt_s) == 0:
            t = t + timedelta(minutes=30)
        hours = t.hour + t.minute / 60.0
        temp = TEMP_REF + 2.2 * math.sin((hours - 9.0) / 24.0 * 2 * math.pi) + rng.normal(0, 0.35)
        f10, f20, n30 = s10[rng.integers(2)], s20[rng.integers(3)], s30[rng.integers(2)]
        torque_reported = TORQUE_NOMINAL + rng.normal(0, 0.45)
        torque_actual = torque_reported + _torque_drift(n30, gidx, cfg)
        clamp = 6.0 + rng.normal(0, 0.15)
        weld = 9.5 + rng.normal(0, 0.25)
        cycle10, cycle20, cycle30 = rng.uniform(48, 62), rng.uniform(55, 70), rng.uniform(40, 52)
        t10 = t
        t20 = t10 + timedelta(seconds=cycle10 + rng.uniform(20, 40))
        t30 = t20 + timedelta(seconds=cycle20 + rng.uniform(60, 140))
        wait50 = rng.uniform(300, 600)
        # Paint shop (separate random stream: does not perturb the base model's draws).
        ap = np.random.default_rng([cfg.seed, 40, gidx])
        booth = ("PB-401", "PB-402")[int(ap.integers(2))]
        paint = str(ap.choice(list(PAINT_MIX), p=list(PAINT_MIX.values())))
        film = float(FILM_NOMINAL_UM + ap.normal(0, 6.0))
        booth_temp = float(23.0 + ap.normal(0, 0.8))
        t40 = t30 + timedelta(seconds=cycle30 + float(ap.uniform(2 * 3600, 3 * 3600)))
        t40_end = t40 + timedelta(minutes=float(ap.uniform(45, 60)))
        t50 = t40_end + timedelta(seconds=wait50)
        route = [
            {"station": "S10", "equipment": f10, "started_at": t10, "ended_at": t10 + timedelta(seconds=cycle10),
             "params": {"clamp_pressure_bar": (round(clamp, 3), "bar"), "cycle_time_s": (round(cycle10, 2), "s")}},
            {"station": "S20", "equipment": f20, "started_at": t20, "ended_at": t20 + timedelta(seconds=cycle20),
             "params": {"weld_current_ka": (round(weld, 3), "kA"), "ambient_temp_c": (round(temp, 2), "degC"),
                        "cycle_time_s": (round(cycle20, 2), "s")}},
            {"station": "S30", "equipment": n30, "started_at": t30, "ended_at": t30 + timedelta(seconds=cycle30),
             "params": {"hinge_torque_nm": (round(torque_reported, 3), "N.m"), "cycle_time_s": (round(cycle30, 2), "s")}},
            {"station": "S40", "equipment": booth, "started_at": t40, "ended_at": t40_end,
             "params": {"film_build_um": (round(film, 2), "um"), "booth_temp_c": (round(booth_temp, 2), "degC")}},
            {"station": "S50", "equipment": "CAM-501", "started_at": t50, "ended_at": t50 + timedelta(seconds=8),
             "params": {}},
        ]
        gaps, scenes = {}, {}
        for loc in LOCATIONS:
            g = (
                loc["nominal_mm"]
                + loc["shift_sensitivity"] * _fixture_offset(f20, gidx, cfg)
                + loc["shift_sensitivity"] * 0.4 * _fixture_offset(f10, gidx, cfg)
                + loc["torque_coeff"] * (torque_actual - TORQUE_NOMINAL)
                + loc["temp_coeff"] * (temp - TEMP_REF)
                + STATIC_FIXTURE_BIAS.get(f20, 0.0)
                + FILM_COEFF_MM_PER_UM * (film - FILM_NOMINAL_UM)
                + rng.normal(0, loc["sigma"])
            )
            gaps[loc["code"]] = round(float(g), 5)
            scenes[loc["code"]] = {
                "angle_deg": float(rng.normal(0, 0.8)),
                "center_offset_mm": float(rng.normal(0, 0.6)),
                "illumination_gradient": float(rng.normal(0, 0.12)),
                "noise_sigma": float(abs(rng.normal(0.016, 0.004))),
                "edge_rolloff_mm": float(abs(rng.normal(0.06, 0.01))),
                "left_level": float(rng.uniform(0.72, 0.82)),
                "right_level": float(rng.uniform(0.70, 0.80)),
                "seed": int(rng.integers(0, 2**31 - 1)),
                # Colour camera appearance (generator 2.0), from the separate stream.
                "paint": paint,
                "gap_style": GAP_STYLE[loc["code"]],
                "orange_peel": float(np.clip(ap.normal(0.03, 0.006), 0.01, 0.06)),
                "crease_y": float(CREASE_Y[loc["code"]] + ap.normal(0, 0.015)),
                "reflection": float(ap.uniform(0.25, 1.0)),
                "reflection_angle_deg": float(ap.uniform(20, 160)),
                "reflection_pos": float(ap.uniform(-0.1, 1.1)),
                "reflection_width_px": float(ap.uniform(30, 75)),
                "dust": int(ap.poisson(1.2)),
            }
        units.append(
            SimUnit(
                index=gidx,
                serial=f"{cfg.serial_prefix}-{gidx + 1:05d}",
                built_at=t10,
                batch=f"COIL-{(gidx // cfg.batch_size) + 1:03d}",
                route=route,
                true_gaps=gaps,
                scene=scenes,
                torque_actual=float(torque_actual),
                paint=paint,
            )
        )

    events = _equipment_events(cfg, units, rng)
    return SimResult(config=cfg, units=units, equipment_events=events)


def _equipment_events(cfg: SimConfig, units: list[SimUnit], rng: np.random.Generator) -> list[dict]:
    """Routine maintenance/calibration plus fault-start events.

    Routine events are generated for *every* resource so that the presence of
    an event near a change point is weak evidence on its own.
    """
    if not units:
        return []
    t0, t1 = units[0].built_at, units[-1].built_at
    span = (t1 - t0).total_seconds()
    events: list[dict] = [
        {"equipment": "CAM-501", "occurred_at": t0 - timedelta(hours=2), "kind": "calibration",
         "description": f"Scale calibration against reference target: {MM_PER_PX} mm/px"},
    ]
    kinds = {
        "fixture": [("maintenance", "Preventive maintenance: clamp inspection"), ("check", "Locator pin wear check")],
        "tool": [("calibration", "Torque transducer verification"), ("maintenance", "Spindle service")],
        "booth": [("maintenance", "Booth filter change"), ("check", "Film-build audit panel")],
    }
    for eq in EQUIPMENT:
        if eq["kind"] == "camera":
            continue
        n = int(rng.integers(2, 4))
        for _ in range(n):
            kind, desc = kinds[eq["kind"]][int(rng.integers(len(kinds[eq["kind"]])))]
            at = t0 + timedelta(seconds=float(rng.uniform(0.05, 0.95) * span))
            events.append({"equipment": eq["code"], "occurred_at": at, "kind": kind, "description": desc})
    by_index = {u.index: u for u in units}
    for f in cfg.faults:
        u = by_index.get(f.start_index)
        if f.with_event and u is not None:
            kind = "changeover" if f.kind == "fixture_shift" else "calibration"
            desc = "Locator pin replaced" if f.kind == "fixture_shift" else "Torque transducer re-zeroed"
            events.append({"equipment": f.target, "occurred_at": u.built_at - timedelta(minutes=5),
                           "kind": kind, "description": desc})
    events.sort(key=lambda e: e["occurred_at"])
    return events
