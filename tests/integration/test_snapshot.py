import json

import pytest

pytestmark = pytest.mark.integration


def _diff(a, b, path=""):
    """Field-level differences between two JSON values (readable failure messages)."""
    if type(a) is not type(b):
        return [(path, a, b)]
    if isinstance(a, dict):
        return [d for k in sorted(set(a) | set(b)) for d in _diff(a.get(k), b.get(k), f"{path}.{k}")]
    if isinstance(a, list):
        if len(a) != len(b):
            return [(path, f"len {len(a)}", f"len {len(b)}")]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in _diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [(path, a, b)]


def test_export_writes_exact_api_responses(client, tmp_path):
    from app.snapshot import export

    meta = export(tmp_path / "snap")
    snap = tmp_path / "snap"
    assert meta["counts"]["inspections"] == 320 and meta["counts"]["units"] == 160
    index = json.loads((snap / "inspections" / "index.json").read_text())
    assert len(index) == 320
    one = index[0]["image_id"]
    assert json.loads((snap / "inspections" / f"{one}.json").read_text()) == client.get(f"/api/v1/inspections/{one}").json()
    assert (snap / "images" / f"{one}.png").read_bytes()[:4] == b"\x89PNG"
    d = _diff(json.loads((snap / "overview.json").read_text()), client.get("/api/v1/overview").json())
    assert not d, d[:5]
    for b in meta["spc_baselines"]:
        assert (snap / "analytics" / "spc" / "FD-FF-M" / f"{b}.json").is_file()
    runs = json.loads((snap / "pipelines" / "index.json").read_text())
    assert all((snap / "pipelines" / f"{r['id']}.errors.json").is_file() for r in runs)
