"""Row-level validation for the MES-style export (pure Python, no database).

Each validator returns either a typed record or a list of rejection reasons.
Within one file, exact duplicate rows are counted as duplicates (not errors);
rows that share a natural key but differ in content are rejected as conflicts.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

PARAM_RANGES: dict[str, tuple[float, float, str]] = {
    "clamp_pressure_bar": (0.0, 12.0, "bar"),
    "weld_current_ka": (0.0, 20.0, "kA"),
    "ambient_temp_c": (-10.0, 50.0, "degC"),
    "hinge_torque_nm": (0.0, 60.0, "N.m"),
    "cycle_time_s": (0.0, 900.0, "s"),
    "film_build_um": (40.0, 250.0, "um"),
    "booth_temp_c": (5.0, 45.0, "degC"),
}


@dataclass
class Reject:
    row_number: int
    field: str | None
    reason: str
    raw: dict


@dataclass
class ValidationReport:
    kind: str
    records: list[dict] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    duplicates: int = 0
    rows_in: int = 0


def parse_ts(value: str | None) -> datetime:
    if value is None or not str(value).strip():
        raise ValueError("missing timestamp")
    v = str(value).strip().replace("Z", "+00:00")
    t = datetime.fromisoformat(v)
    if t.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return t.astimezone(UTC)


def parse_float(value: str | None) -> float:
    if value is None or not str(value).strip():
        raise ValueError("missing number")
    x = float(str(value).strip())
    if not math.isfinite(x):
        raise ValueError("non-finite number")
    return x


@dataclass(frozen=True)
class Context:
    stations: frozenset[str]
    equipment: dict[str, str]  # code -> station
    serials: frozenset[str]
    locations: frozenset[str]
    calibrations: frozenset[str]
    paints: frozenset[str] = frozenset()


def _require(raw: dict, fields: Iterable[str]) -> list[tuple[str, str]]:
    return [(f, "missing value") for f in fields if not str(raw.get(f) or "").strip()]


def validate_units(raw: dict, ctx: Context) -> tuple[dict | None, list[tuple[str | None, str]]]:
    errs: list[tuple[str | None, str]] = list(_require(raw, ["serial", "line", "built_at", "batch"]))
    paint = (raw.get("paint") or "").strip() or None  # optional column (older exports have none)
    if paint is not None and ctx.paints and paint not in ctx.paints:
        errs.append(("paint", f"unknown paint code {paint!r}"))
    rec = None
    if not errs:
        try:
            rec = {"serial": raw["serial"].strip(), "line": raw["line"].strip(), "built_at": parse_ts(raw["built_at"]),
                   "batch": raw["batch"].strip(), "paint": paint}
        except ValueError as e:
            errs.append(("built_at", str(e)))
    return rec, errs


def validate_production_event(raw: dict, ctx: Context):
    errs: list[tuple[str | None, str]] = list(_require(raw, ["serial", "station", "equipment", "started_at", "ended_at"]))
    if errs:
        return None, errs
    if raw["station"] not in ctx.stations:
        errs.append(("station", f"unknown station code {raw['station']!r}"))
    if raw["equipment"] not in ctx.equipment:
        errs.append(("equipment", f"unknown equipment {raw['equipment']!r}"))
    elif raw["station"] in ctx.stations and ctx.equipment[raw["equipment"]] != raw["station"]:
        errs.append(("equipment", f"{raw['equipment']} does not belong to station {raw['station']}"))
    if raw["serial"] not in ctx.serials:
        errs.append(("serial", f"unit {raw['serial']!r} not present in units export"))
    try:
        s, e = parse_ts(raw["started_at"]), parse_ts(raw["ended_at"])
        if e < s:
            errs.append(("ended_at", "ended before it started"))
    except ValueError as ex:
        errs.append(("started_at", str(ex)))
        s = e = None  # type: ignore[assignment]
    if errs:
        return None, errs
    return {"serial": raw["serial"], "station": raw["station"], "equipment": raw["equipment"], "started_at": s,
            "ended_at": e}, []


def validate_parameter(raw: dict, ctx: Context):
    errs: list[tuple[str | None, str]] = list(_require(raw, ["serial", "station", "parameter", "value", "unit"]))
    if errs:
        return None, errs
    name = raw["parameter"]
    if name not in PARAM_RANGES:
        errs.append(("parameter", f"unknown parameter {name!r}"))
    if raw["station"] not in ctx.stations:
        errs.append(("station", f"unknown station code {raw['station']!r}"))
    if raw["serial"] not in ctx.serials:
        errs.append(("serial", f"unit {raw['serial']!r} not present in units export"))
    try:
        v = parse_float(raw["value"])
        if name in PARAM_RANGES:
            lo, hi, unit = PARAM_RANGES[name]
            if not lo <= v <= hi:
                errs.append(("value", f"{name}={v} outside plausible range [{lo}, {hi}]"))
            if raw["unit"] != unit:
                errs.append(("unit", f"expected unit {unit!r}, got {raw['unit']!r}"))
    except ValueError as ex:
        errs.append(("value", f"not a number: {raw['value']!r} ({ex})"))
        v = None  # type: ignore[assignment]
    if errs:
        return None, errs
    return {"serial": raw["serial"], "station": raw["station"], "parameter": name, "value": v, "unit": raw["unit"]}, []


def validate_equipment_event(raw: dict, ctx: Context):
    errs: list[tuple[str | None, str]] = list(_require(raw, ["equipment", "occurred_at", "kind"]))
    if errs:
        return None, errs
    if raw["equipment"] not in ctx.equipment:
        errs.append(("equipment", f"unknown equipment {raw['equipment']!r}"))
    try:
        t = parse_ts(raw["occurred_at"])
    except ValueError as ex:
        return None, [("occurred_at", str(ex))]
    if errs:
        return None, errs
    return {"equipment": raw["equipment"], "occurred_at": t, "kind": raw["kind"],
            "description": raw.get("description") or ""}, []


def validate_inspection(raw: dict, ctx: Context):
    errs: list[tuple[str | None, str]] = list(
        _require(raw, ["image_file", "serial", "location", "camera", "captured_at", "calibration_ref"]))
    if errs:
        return None, errs
    if raw["serial"] not in ctx.serials:
        errs.append(("serial", f"unit {raw['serial']!r} not present in units export"))
    if raw["location"] not in ctx.locations:
        errs.append(("location", f"unknown measurement location {raw['location']!r}"))
    if raw["calibration_ref"] not in ctx.calibrations:
        errs.append(("calibration_ref", f"unknown calibration {raw['calibration_ref']!r}"))
    if not raw["image_file"].startswith("images/") or ".." in raw["image_file"]:
        errs.append(("image_file", "image path must be inside images/"))
    try:
        t = parse_ts(raw["captured_at"])
    except ValueError as ex:
        errs.append(("captured_at", str(ex)))
        t = None  # type: ignore[assignment]
    if errs:
        return None, errs
    return {"image_file": raw["image_file"], "serial": raw["serial"], "location": raw["location"],
            "camera": raw["camera"], "captured_at": t, "calibration_ref": raw["calibration_ref"]}, []


VALIDATORS = {
    "units": (validate_units, ("serial",)),
    "production_events": (validate_production_event, ("serial", "station")),
    "process_parameters": (validate_parameter, ("serial", "station", "parameter")),
    "equipment_events": (validate_equipment_event, ("equipment", "occurred_at", "kind")),
    "inspections": (validate_inspection, ("serial", "location")),
}


def validate_rows(kind: str, rows: Iterable[dict], ctx: Context) -> ValidationReport:
    fn, key_fields = VALIDATORS[kind]
    rep = ValidationReport(kind=kind)
    seen: dict[tuple, dict] = {}
    for i, raw in enumerate(rows, start=2):  # row 1 is the CSV header
        rep.rows_in += 1
        rec, errs = fn(raw, ctx)
        if errs:
            for f, reason in errs:
                rep.rejects.append(Reject(i, f, reason, dict(raw)))
            continue
        assert rec is not None
        key = tuple(rec[k] for k in key_fields)
        if key in seen:
            if seen[key] == rec:
                rep.duplicates += 1
            else:
                rep.rejects.append(Reject(i, None, f"conflicting duplicate for key {key}", dict(raw)))
            continue
        seen[key] = rec
        rep.records.append(rec)
    return rep
