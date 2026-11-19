import pytest
from sqlalchemy import select

from app.domain import models as m

from .conftest import KEY

pytestmark = pytest.mark.integration
V1 = "/api/v1"


def first_oot(client):
    r = client.get(f"{V1}/inspections", params={"dataset": KEY, "status": "out_of_tolerance", "order": "asc",
                                                "location": "FD-FF-M", "page_size": 50})
    items = r.json()["items"]
    assert items, "fixture fault should create out-of-tolerance inspections"
    return items[min(2, len(items) - 1)]


def test_health(client):
    r = client.get(f"{V1}/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_pagination_and_filters(client):
    r1 = client.get(f"{V1}/inspections", params={"dataset": KEY, "page_size": 7, "page": 1})
    r2 = client.get(f"{V1}/inspections", params={"dataset": KEY, "page_size": 7, "page": 2})
    a, b = r1.json(), r2.json()
    assert a["total"] == b["total"] == 320 and len(a["items"]) == 7
    assert not {i["image_id"] for i in a["items"]} & {i["image_id"] for i in b["items"]}
    oot = client.get(f"{V1}/inspections", params={"dataset": KEY, "status": "out_of_tolerance"}).json()
    assert all(i["tolerance_status"] in ("out_low", "out_high") for i in oot["items"])


def test_structured_validation_errors(client):
    r = client.get(f"{V1}/inspections", params={"page_size": 10_000})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "validation_error" and body["error"]["details"]
    r = client.get(f"{V1}/inspections/999999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.post(f"{V1}/investigations", json={"image_id": "x"}).status_code == 422


def test_inspection_detail_is_associated_with_correct_unit(client, db):
    item = client.get(f"{V1}/inspections", params={"dataset": KEY, "page_size": 1}).json()["items"][0]
    d = client.get(f"{V1}/inspections/{item['image_id']}").json()
    img = db.get(m.InspectionImage, item["image_id"])
    unit = db.get(m.ProductionUnit, img.unit_id)
    assert d["serial"] == unit.serial and d["unit_id"] == unit.id
    run = d["current_run"]
    assert run["status"] == "ok" and run["overlay"]["rows"] and run["measurement"]["gap_mm"] > 0
    assert d["provenance"]["simulated"] is True and d["calibration"]["mm_per_px"] == 0.025
    png = client.get(d["image_url"])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"


def test_interactive_rerun_does_not_replace_pipeline_result(client):
    item = client.get(f"{V1}/inspections", params={"dataset": KEY, "page_size": 1}).json()["items"][0]
    r = client.post(f"{V1}/inspections/{item['image_id']}/runs", json={"smoothing_sigma_px": 2.5, "row_step": 8})
    assert r.status_code == 201 and r.json()["trigger"] == "interactive" and not r.json()["is_current"]
    d = client.get(f"{V1}/inspections/{item['image_id']}").json()
    assert d["current_run"]["trigger"] == "pipeline" and len(d["runs"]) >= 2
    bad = client.post(f"{V1}/inspections/{item['image_id']}/runs", json={"row_step": 0})
    assert bad.status_code == 422


def test_ground_truth_is_separate_endpoint(client):
    item = client.get(f"{V1}/inspections", params={"dataset": KEY, "page_size": 1}).json()["items"][0]
    detail = client.get(f"{V1}/inspections/{item['image_id']}").json()
    assert "true_gap_mm" not in str(detail)
    gt = client.get(f"{V1}/inspections/{item['image_id']}/ground-truth").json()
    assert gt["available"] and abs(gt["error_um"]) < 60


def test_investigation_stores_and_returns_evidence(client, seeded):
    oot = first_oot(client)
    r = client.post(f"{V1}/investigations", json={"image_id": oot["image_id"]})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "shift_detected"
    top = inv["hypotheses"][0]
    assert top["level"] == "FX-202" and top["significant"] and top["rank"] == 1
    assert inv["limitations"] and inv["evidence"]["series_snapshot"]["serial"]
    again = client.get(f"{V1}/investigations/{inv['id']}").json()
    assert again["hypotheses"] == inv["hypotheses"]
    # idempotent for the same trigger + params
    assert client.post(f"{V1}/investigations", json={"image_id": oot["image_id"]}).json()["id"] == inv["id"]
    md = client.get(f"{V1}/reports/investigations/{inv['id']}.md")
    assert md.status_code == 200 and "FX-202" in md.text and "not confirmed root causes" in md.text
    rep = client.get(f"{V1}/reports/investigations/{inv['id']}.json").json()
    assert len(rep["content_sha256"]) == 64


def test_investigation_requires_out_of_tolerance(client):
    ok = client.get(f"{V1}/inspections", params={"dataset": KEY, "status": "in_tolerance", "page_size": 1}).json()
    r = client.post(f"{V1}/investigations", json={"image_id": ok["items"][0]["image_id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "within_tolerance"


def test_traceability_route(client):
    item = client.get(f"{V1}/inspections", params={"dataset": KEY, "page_size": 1}).json()["items"][0]
    t = client.get(f"{V1}/units/{item['unit_id']}/traceability").json()
    assert t["serial"] == item["serial"] and t["provenance"]["simulated"]
    assert [s["station"] for s in t["route"]] == sorted(s["station"] for s in t["route"])
    assert client.get(f"{V1}/traceability", params={"serial": item["serial"], "dataset": KEY}).json()["unit_id"] == item["unit_id"]


def test_spc_and_station_comparison(client):
    s = client.get(f"{V1}/analytics/spc", params={"dataset": KEY, "location": "FD-FF-M", "baseline_n": 60}).json()
    assert s["n"] == len(s["values"]) and s["ucl"] > s["center"] > s["lcl"]
    assert s["first_signal_index"] is not None and s["first_signal_index"] >= 60
    st = client.get(f"{V1}/analytics/stations/S20", params={"dataset": KEY, "location": "FD-FF-M"}).json()
    means = {g["equipment"]: g["mean_mm"] for g in st["groups"]}
    assert max(means, key=means.get) == "FX-202"
    assert client.get(f"{V1}/analytics/stations/S99", params={"location": "FD-FF-M", "dataset": KEY}).status_code == 422


def test_pipeline_monitor_reflects_actual_runs(client, db):
    from app.pipelines.mes_import import run_mes_import

    run_mes_import("raw/does-not-exist", "missing-ds")  # a genuine failed execution
    runs = client.get(f"{V1}/pipelines/runs", params={"page_size": 100}).json()
    ids = {r["id"] for r in runs["items"]}
    assert set(db.scalars(select(m.PipelineRun.id))) == ids
    failed = next(r for r in runs["items"] if r["status"] == "failed")
    detail = client.get(f"{V1}/pipelines/runs/{failed['id']}").json()
    assert "manifest.json not found" in detail["error_message"] and detail["records_loaded"] == 0
    errs = client.get(f"{V1}/pipelines/runs/{runs['items'][-1]['id']}/errors").json()
    assert errs["total"] >= 0


def test_corrective_action_job_lifecycle(client):
    from app.services.jobs import run_one

    oot = first_oot(client)
    inv = client.post(f"{V1}/investigations", json={"image_id": oot["image_id"]}).json()
    bad = client.post(f"{V1}/simulations/corrective-actions",
                      json={"investigation_id": inv["id"], "target_code": "NR-301", "kind": "realign_fixture"})
    assert bad.status_code == 422
    r = client.post(f"{V1}/simulations/corrective-actions",
                    json={"investigation_id": inv["id"], "target_code": "FX-202", "n_units": 40, "seed": 3})
    assert r.status_code == 202 and r.json()["job"]["status"] == "queued"
    assert run_one()
    v = client.get(f"{V1}/simulations/verifications/{r.json()['id']}").json()
    assert v["status"] == "succeeded" and v["job"]["status"] == "succeeded"
    res = v["result"]
    assert res["simulated"] is True and res["paired_mean_change_mm"] < -0.05
    assert res["adjusted"]["oot_rate"] <= res["baseline"]["oot_rate"]
