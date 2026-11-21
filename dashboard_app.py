#!/usr/bin/env python3
"""Compatibility entry point for the standalone control plane."""

import os

from control_plane import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
