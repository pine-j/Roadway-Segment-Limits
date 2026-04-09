#!/usr/bin/env python3
"""Backward-compatible entry point for screenshot capture."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("visual-review-screenshots.py")), run_name="__main__")
