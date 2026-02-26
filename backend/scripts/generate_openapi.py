#!/usr/bin/env python3
"""
Generate OpenAPI (Swagger) spec for ForexMind API.
Run from project root: python backend/scripts/generate_openapi.py
Output: backend/openapi.json (localhost server)
"""
import json
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Avoid heavy imports during spec generation by mocking if needed
from main import app

out_path = _backend / "openapi.json"
spec = app.openapi()
with open(out_path, "w") as f:
    json.dump(spec, f, indent=2)

print(f"Wrote {out_path}")
sys.exit(0)
