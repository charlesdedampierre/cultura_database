"""Start the Historical Polity Visualizer server.

Usage:
    python start.py              # starts on port 8000
    python start.py 3000         # starts on port 3000
"""

import sys
import uvicorn

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

print(f"\n  Historical Polity Visualizer")
print(f"  http://localhost:{port}\n")

uvicorn.run("backend.main:app", host="0.0.0.0", port=port)
