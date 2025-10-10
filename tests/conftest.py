"""
Pytest configuration: ensure project root is on sys.path for imports.

Several tests import the local `synonyms` package directly. When running tests
from certain IDEs or subdirectories, the repository root might not be on the
Python module search path. This hook prepends the repo root so imports work
consistently (e.g., `from synonyms.models import ...`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _add_repo_root_to_sys_path() -> None:
    # tests/ -> repo root
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


_add_repo_root_to_sys_path()

