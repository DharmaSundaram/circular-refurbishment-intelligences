import sys
from pathlib import Path

# Ensure frontend root directory is on sys.path
frontend_dir = Path(__file__).resolve().parent.parent
if str(frontend_dir) not in sys.path:
    sys.path.insert(0, str(frontend_dir))
