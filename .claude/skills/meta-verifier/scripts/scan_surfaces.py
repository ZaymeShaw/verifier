#!/usr/bin/env python3
"""Scan a project directory for verifiable surfaces and output JSON.

Usage:
  python scan_surfaces.py [project_root]  # defaults to cwd
  echo '{"project_root": "/path/to/project"}' | python scan_surfaces.py

Output: JSON with frontend_pages, api_routes, demand_docs, protocol_docs, skill_docs, readme, project_configs
"""

import json
import sys
from pathlib import Path

# Ensure sibling meta_verifier.py is importable
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))


def scan(project_root: str) -> dict:
    from meta_verifier import MetaVerifierProjectDiscovery

    discovery = MetaVerifierProjectDiscovery(Path(project_root))
    artifacts = discovery.discover_artifacts()

    # Add summary counts
    summary = {k: len(v) for k, v in artifacts.items()}
    return {"project_root": project_root, "summary": summary, "artifacts": artifacts}


if __name__ == "__main__":
    project_root = None
    # Try reading from arg
    if len(sys.argv) > 1:
        project_root = sys.argv[1]
    # Try reading from stdin JSON
    elif not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
            project_root = data.get("project_root", None)
        except (json.JSONDecodeError, AttributeError):
            pass

    root = project_root or str(Path.cwd())
    result = scan(root)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False, default=str)
