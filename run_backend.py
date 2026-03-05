#!/usr/bin/env python3
"""
Run the ForexMind backend from project root.
Usage: python run_backend.py
Or:    python run_backend.py --port 8001
"""
import os
import sys
from pathlib import Path

# Ensure backend is on path when run from project root
_root = Path(__file__).resolve().parent
_backend = _root / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

os.chdir(_backend)

if __name__ == "__main__":
    import uvicorn
    port = 8000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
