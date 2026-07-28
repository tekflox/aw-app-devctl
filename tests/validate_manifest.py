#!/usr/bin/env python3
"""Validates aw-app.json against schemas/aw-app.schema.json. Run with the
AW venv (jsonschema is installed there): .venv/aw/bin/python tests/validate_manifest.py
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent

manifest = json.loads((ROOT / "aw-app.json").read_text())
schema = json.loads((ROOT / "schemas" / "aw-app.schema.json").read_text())

jsonschema.validate(instance=manifest, schema=schema)

# The window spec referenced from contributes.windows must exist.
for win in manifest["contributes"].get("windows", []):
    spec_path = ROOT / win["body"]["spec"]
    assert spec_path.is_file(), f"missing window spec: {spec_path}"

print("OK: aw-app.json is valid")
