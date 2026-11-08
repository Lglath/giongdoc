#!/usr/bin/env python3
"""Development launcher for GiongDoc (also the PyInstaller entry script).

    python run.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from giongdoc.ui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
