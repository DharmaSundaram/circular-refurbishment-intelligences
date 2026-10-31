"""Vercel Serverless Function entry point for Refurbishment Intelligence.

Integrates the Flask WSGI application with Vercel's Python runtime.
"""

import os
import sys
from pathlib import Path

# Add backend directory to sys.path so modules (models, services, config, extensions) are accessible
root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Ensure VERCEL environment variable is set
os.environ.setdefault("VERCEL", "1")

from app import create_app

# Point dist to public directory if present, otherwise frontend/ui
public_dir = root_dir / "public"
frontend_ui = root_dir / "frontend" / "ui"
dist_dir = public_dir if (public_dir / "index.html").is_file() else frontend_ui

# Create Flask application instance (named 'app' for Vercel WSGI)
app = create_app(dist_directory=dist_dir)

if __name__ == "__main__":
    app.run()
