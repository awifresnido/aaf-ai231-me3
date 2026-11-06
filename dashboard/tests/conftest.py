import sys
from pathlib import Path

# Make `backend` importable when running `pytest dashboard/tests` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
