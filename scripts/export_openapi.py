"""Write the API's OpenAPI document to docs/openapi.json (input for the generated TS client types)."""

import json
from pathlib import Path

from app.main import create_app

out = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=1) + "\n")
print(f"wrote {out}")
