"""-I entry point: import only the root-owned worker installation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worker import main

raise SystemExit(main())
