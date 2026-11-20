from fittrace.etl.validation import Context, validate_rows

CTX = Context(stations=frozenset({"S10", "S20"}), equipment={"FX-101": "S10", "FX-201": "S20"},
              serials=frozenset({"U1", "U2"}), locations=frozenset({"L1"}), calibrations=frozenset({"C1"}))


def param(**kw):
    return {"serial": "U1", "station": "S10", "parameter": "clamp_pressure_bar", "value": "6.1", "unit": "bar", **kw}


def test_valid_parameter_row():
    rep = validate_rows("process_parameters", [param()], CTX)
    assert len(rep.records) == 1 and rep.records[0]["value"] == 6.1 and not rep.rejects


def test_each_defect_kind_is_rejected_with_field():
    rows = [param(value="6,1x"), param(value="-999", serial="U2"), param(serial="NOPE"), param(value="", serial="U2",
            station="S20", parameter="weld_current_ka", unit="kA"), param(unit="psi", station="S20")]
    rep = validate_rows("process_parameters", rows, CTX)
    fields = sorted({r.field for r in rep.rejects})
    assert not rep.records
    assert {"value", "serial", "unit"} <= set(fields)
    assert {r.row_number for r in rep.rejects} == {2, 3, 4, 5, 6}


def test_exact_duplicates_are_counted_not_rejected():
    rep = validate_rows("process_parameters", [param(), param()], CTX)
    assert len(rep.records) == 1 and rep.duplicates == 1 and not rep.rejects


def test_conflicting_duplicate_is_rejected():
    rep = validate_rows("process_parameters", [param(), param(value="7.0")], CTX)
    assert len(rep.records) == 1 and len(rep.rejects) == 1 and "conflicting" in rep.rejects[0].reason


def test_event_station_equipment_consistency_and_order():
    good = {"serial": "U1", "station": "S10", "equipment": "FX-101", "started_at": "2026-01-01T00:00:00Z",
            "ended_at": "2026-01-01T00:01:00Z"}
    wrong_station = {**good, "equipment": "FX-201"}
    reversed_time = {**good, "serial": "U2", "ended_at": "2025-12-31T00:00:00Z"}
    naive = {**good, "serial": "U2", "started_at": "2026-01-01T00:00:00"}
    rep = validate_rows("production_events", [good, wrong_station, reversed_time, naive], CTX)
    assert len(rep.records) == 1
    reasons = " ".join(r.reason for r in rep.rejects)
    assert "does not belong" in reasons and "ended before" in reasons and "without timezone" in reasons


def test_inspection_path_traversal_rejected():
    row = {"image_file": "images/../../etc/passwd", "serial": "U1", "location": "L1", "camera": "CAM",
           "captured_at": "2026-01-01T00:00:00Z", "calibration_ref": "C1"}
    rep = validate_rows("inspections", [row], CTX)
    assert rep.rejects and rep.rejects[0].field == "image_file"
