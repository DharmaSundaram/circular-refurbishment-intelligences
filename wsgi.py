"""Root WSGI entry point for Refurbishment Intelligence platform.
Enables execution from either repository root or backend/ directory.
"""

import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from werkzeug.middleware.proxy_fix import ProxyFix
from app import create_app

app = create_app()
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", "5000")))
    app.run(host="0.0.0.0", port=port)

