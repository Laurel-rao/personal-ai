"""Pre-cache DMM official covers (and frame fallbacks) for every local video.

Run with: .venv/bin/python tools/warm_video_covers.py
The app also runs this automatically on VIDEO_COVER_REFRESH_SECONDS (default daily).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


if __name__ == "__main__":
    print(server._warm_video_covers())
