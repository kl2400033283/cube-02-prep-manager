"""Validate against the vendored CUBE Round 3 schemas (contract/round3, see SOURCE_COMMIT.txt)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import List

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "contract" / "round3"


@lru_cache(maxsize=None)
def _validator(name: str):
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    registry = Registry()
    for path in SCHEMA_DIR.glob("*.schema.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))
    doc = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(doc, registry=registry, format_checker=FormatChecker())


def errors(name: str, instance) -> List[str]:
    """Human-readable schema violations (empty list = valid)."""
    if not isinstance(instance, dict):
        return ["<root>: must be an object"]
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(_validator(name).iter_errors(instance), key=lambda e: list(e.absolute_path))]
