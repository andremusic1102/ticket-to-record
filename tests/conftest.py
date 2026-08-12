from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is tooling, not part of the shipped package, so it is not on the
# import path by default. Tests still need to cover it — an unverified guard is
# not a guard.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
