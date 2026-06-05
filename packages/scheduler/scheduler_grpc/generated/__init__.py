from __future__ import annotations

import sys
from pathlib import Path

_generated_dir = str(Path(__file__).resolve().parent)
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)
