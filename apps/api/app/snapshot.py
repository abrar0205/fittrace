"""Static snapshot for GitHub Pages.

GitHub Pages serves static files only, so the public demo is a *snapshot*:

1. ``prepare``: run an investigation for every out-of-tolerance inspection and a
   simulated verification of each investigation's top-ranked equipment (plus one
   deliberately wrong target), using the normal services and job worker.
2. ``export``: request every view the web app needs through the real API (FastAPI
   TestClient, so the files are exactly the API's responses) and write them as JSON,
   together with the inspection images and benchmark case images.

Nothing is computed in this module: it only orchestrates and serialises results
produced by the pipelines, services and jobs.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import session_scope
from app.domain import models as m

logger = logging.getLogger("fittrace.snapshot")
V1 = "/api/v1"
SPC_BASELINES = [60, 80, 100, 120, 150, 200]
STATIONS = ["S10", "S20", "S30", "S40"]


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def _ok(r, what: str):
    if r.status_code >= 400:
        raise RuntimeError(f"{what}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def prepare(n_units: int = 120) -> dict:
    """Create investigations and verification runs (idempotent)."""
    from app.services.jobs import run_one

    c = _client()
    oot = []
    page = 1
    while True:
        body = _ok(c.get(f"{V1}/inspections", params={"status": "out_of_tolerance", "order": "asc", "page": page,
                                                      "page_size": 500}), "list out-of-tolerance")
        oot += body["items"]
        if page * body["page_size"] >= body["total"]:
            break
        page += 1
    invs = []
    for it in oot:
        r = c.post(f"{V1}/investigations", json={"image_id": it["image_id"]})
        if r.status_code == 409:  # e.g. too little history; recorded as a skip, not hidden
            logger.warning("investigation skipped for %s: %s", it["serial"], r.json()["error"]["message"])
            continue
        invs.append(_ok(r, f"investigation for {it['serial']}"))
    created = 0
    wrong_shown = False
    for inv in invs:
        done = {v["target_code"] for v in inv["verification_runs"]}
        top = next((h for h in inv["hypotheses"] if h["significant"] and h["factor_type"] == "equipment"), None)
        targets = [top["level"]] if top else []
        if top and not wrong_shown:
            # One deliberately wrong target (on the first investigation that names a contributor)
            # shows that acting on an innocent resource changes nothing.
            wrong_shown = True
            wrong = next((h["level"] for h in inv["hypotheses"]
                          if h["factor_type"] == "equipment" and h["level"] != top["level"]
                          and str(h["level"]).startswith(str(top["level"])[:4])), None)
            if wrong:
                targets.append(wrong)
        for t in targets:
            if t in done:
                continue
            kind = "realign_fixture" if t.startswith("FX") else "recalibrate_tool"
            _ok(c.post(f"{V1}/simulations/corrective-actions",
                       json={"investigation_id": inv["id"], "target_code": t, "kind": kind, "n_units": n_units, "seed": 1}),
                f"verification {inv['id']} {t}")
            while run_one():
                pass
            created += 1
    return {"out_of_tolerance": len(oot), "investigations": len(invs), "verifications_created": created}


def _write(out: Path, rel: str, data) -> None:
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (bytes, bytearray)):
        p.write_bytes(data)
    elif isinstance(data, str):
        p.write_text(data)
    else:
        p.write_text(json.dumps(data, separators=(",", ":"), default=str))


def _all_pages(c: TestClient, path: str, params: dict | None = None, size: int = 500) -> list:
    items, page = [], 1
    while True:
        body = _ok(c.get(path, params={**(params or {}), "page": page, "page_size": size}), path)
        items += body["items"]
        if page * size >= body["total"]:
            return items
        page += 1


def export(out_dir: str | Path) -> dict:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    c = _client()
    counts: dict[str, int] = {}

    for name in ("health", "datasets", "locations", "overview"):
        _write(out, f"{name}.json", _ok(c.get(f"{V1}/{name}"), name))
    locations = [loc["code"] for loc in json.loads((out / "locations.json").read_text())]

    insp = _all_pages(c, f"{V1}/inspections")
    _write(out, "inspections/index.json", insp)
    for it in insp:
        iid = it["image_id"]
        _write(out, f"inspections/{iid}.json", _ok(c.get(f"{V1}/inspections/{iid}"), f"inspection {iid}"))
        _write(out, f"inspections/{iid}.gt.json", _ok(c.get(f"{V1}/inspections/{iid}/ground-truth"), f"gt {iid}"))
        img = c.get(f"{V1}/inspections/{iid}/image")
        if img.status_code == 200:
            _write(out, f"images/{iid}.png", img.content)
    counts["inspections"] = len(insp)

    units = sorted({it["unit_id"] for it in insp})
    for uid in units:
        _write(out, f"units/{uid}.json", _ok(c.get(f"{V1}/units/{uid}/traceability"), f"unit {uid}"))
    counts["units"] = len(units)

    for loc in locations:
        for b in SPC_BASELINES:
            r = c.get(f"{V1}/analytics/spc", params={"location": loc, "baseline_n": b})
            if r.status_code == 200:
                _write(out, f"analytics/spc/{loc}/{b}.json", r.json())
        for st in STATIONS:
            _write(out, f"analytics/stations/{loc}/{st}.json",
                   _ok(c.get(f"{V1}/analytics/stations/{st}", params={"location": loc}), f"station {loc} {st}"))

    invs = _all_pages(c, f"{V1}/investigations", size=500)
    _write(out, "investigations/index.json", invs)
    ver_ids: set[int] = set()
    for inv in invs:
        d = _ok(c.get(f"{V1}/investigations/{inv['id']}"), f"investigation {inv['id']}")
        _write(out, f"investigations/{inv['id']}.json", d)
        ver_ids |= {v["id"] for v in d["verification_runs"]}
        _write(out, f"reports/{inv['id']}.json", _ok(c.get(f"{V1}/reports/investigations/{inv['id']}.json"), "report"))
        _write(out, f"reports/{inv['id']}.md", c.get(f"{V1}/reports/investigations/{inv['id']}.md").text)
    for vid in sorted(ver_ids):
        _write(out, f"verifications/{vid}.json", _ok(c.get(f"{V1}/simulations/verifications/{vid}"), f"verification {vid}"))
    counts["investigations"], counts["verifications"] = len(invs), len(ver_ids)

    runs = _all_pages(c, f"{V1}/pipelines/runs", size=500)
    _write(out, "pipelines/index.json", runs)
    for r in runs:
        _write(out, f"pipelines/{r['id']}.json", _ok(c.get(f"{V1}/pipelines/runs/{r['id']}"), f"run {r['id']}"))
        _write(out, f"pipelines/{r['id']}.errors.json", _all_pages(c, f"{V1}/pipelines/runs/{r['id']}/errors"))
    counts["pipeline_runs"] = len(runs)

    for kind in ("vision", "investigation"):
        r = c.get(f"{V1}/evaluation/{kind}")
        if r.status_code == 200:
            _write(out, f"evaluation/{kind}.json", r.json())
            if kind == "vision":
                for i in range(len(r.json()["summary"].get("cases", []))):
                    _write(out, f"evaluation/cases/{i}.png", c.get(f"{V1}/evaluation/vision/cases/{i}/image").content)

    with session_scope() as db:
        ds = db.scalar(select(m.Dataset).order_by(m.Dataset.id).limit(1))
    env = os.environ
    run_url = None
    if env.get("GITHUB_RUN_ID"):
        run_url = f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    meta = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "commit": env.get("GITHUB_SHA", "")[:7] or None,
            "run_url": run_url,
            "dataset": ds.key if ds else None, "spc_baselines": SPC_BASELINES, "counts": counts}
    _write(out, "meta.json", meta)
    return meta
