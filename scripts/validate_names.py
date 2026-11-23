#!/usr/bin/env python3
"""Compatibility wrapper (Stage 2). Naming rules now live in tools/registry/naming.py and are
tested by tests/test_naming.py; registry-level duplicate detection is in tools/registry/validate.py
(R01 duplicate keys, R04 duplicate files, R12 duplicate deployments / derived-name collisions).

Usage: python3 scripts/validate_names.py <customer> <product> <env>
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools.registry.naming import derived_names, validate_names  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    errs = validate_names(*sys.argv[1:])
    print("\n".join(errs) if errs else f"valid: {derived_names(*sys.argv[1:])['sa_ids']}")
    sys.exit(1 if errs else 0)
