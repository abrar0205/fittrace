"""Reproducible investigation reports (JSON and Markdown)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.services.investigations import get_investigation
from fittrace import __version__


def investigation_report(db: Session, inv_id: int) -> dict:
    inv = get_investigation(db, inv_id)
    body = {k: v for k, v in inv.items() if k != "evidence"}
    report = {
        "report_format": "fittrace-investigation-report/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "software": {"fittrace": __version__, "method": inv["method"], "method_version": inv["method_version"]},
        "reproducibility": {
            "inputs": "current pipeline measurements of the triggering location for units built up to the trigger",
            "params": inv["params"],
            "note": "Re-running the method with the same params and inputs reproduces the ranking "
                    "(the permutation test is seeded).",
        },
        "investigation": body,
    }
    canonical = json.dumps(body, sort_keys=True, default=str).encode()
    report["content_sha256"] = hashlib.sha256(canonical).hexdigest()
    return report


def _f(x, nd=3, unit=""):
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def investigation_markdown(db: Session, inv_id: int) -> str:
    r = investigation_report(db, inv_id)
    inv = r["investigation"]
    t, cp, loc = inv["trigger"], inv["change_point"], inv["location"]
    lines = [
        f"# FitTrace investigation #{inv['id']}",
        "",
        f"> {inv['provenance']['statement']}",
        "",
        f"- **Trigger:** unit `{t['serial']}`, location `{loc['code']}` ({loc['name']}), gap {_f(t['gap_mm'])} mm "
        f"(spec {loc['lsl_mm']:.2f}-{loc['usl_mm']:.2f} mm, status `{t['status']}`)",
        f"- **Method:** `{inv['method']}` v{inv['method_version']}, params `{json.dumps(inv['params'])}`",
        f"- **Conclusion:** `{inv['status']}`",
    ]
    if cp.get("found"):
        lines.append(f"- **Change point:** unit `{cp.get('serial')}` ({cp.get('built_at')}), mean shift "
                     f"{_f(cp.get('delta'), 3)} mm, permutation p = {_f(cp.get('p_value'), 4)}")
    lines += ["", "## Ranked candidate contributors", "",
              "| Rank | Factor | Level | Effect (mm) | 95% CI | q | Explains | Significant |",
              "|---:|---|---|---:|---|---:|---:|:---:|"]
    for h in inv["hypotheses"]:
        if h["status"] != "tested":
            continue
        ci = f"[{_f(h['ci_low'])}, {_f(h['ci_high'])}]"
        ef = "n/a" if h["explained_fraction"] is None else f"{h['explained_fraction']:.0%}"
        lines.append(f"| {h['rank']} | {h['factor']} | {h['level'] or '-'} | {_f(h['effect_mm'])} | {ci} | "
                     f"{_f(h['q_value'], 4)} | {ef} | {'yes' if h['significant'] else 'no'} |")
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in inv["limitations"]]
    lines += ["", "---", f"Generated {r['generated_at']} by FitTrace {r['software']['fittrace']}. "
              f"Content SHA-256 `{r['content_sha256']}`."]
    return "\n".join(lines) + "\n"
