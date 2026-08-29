"""Private runtime locations for Tasty Coach."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
raw = os.environ.get("TASTY_COACH_PRIVATE_DATA_ROOT")
PRIVATE_DATA_ROOT = Path(raw).expanduser() if raw else PROJECT_ROOT
if not PRIVATE_DATA_ROOT.is_absolute():
    PRIVATE_DATA_ROOT = PROJECT_ROOT / PRIVATE_DATA_ROOT

RUNTIME_LOGS_DIR = PRIVATE_DATA_ROOT / "runtime" / "logs"
ARTIFACTS_DIR = PRIVATE_DATA_ROOT / "artifacts"
