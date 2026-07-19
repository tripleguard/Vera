import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(ROOT / "tests"), "-ra", "-p", "no:cacheprovider"]))
