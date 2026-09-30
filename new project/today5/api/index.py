"""Vercel entry point: every request is routed here (see vercel.json) and handled by the same code as local."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import Handler  # noqa: E402


class handler(Handler):
    pass
