#!/usr/bin/env python3
"""Backward-compatible wrapper: deploy Hire Tech custom-talent scripts."""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "deploy_custom_talent_campaigns.py"
    raise SystemExit(
        subprocess.call([sys.executable, str(script), "Hire Tech Partners"], env=None)
    )
