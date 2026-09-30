"""Run the daily automation once by hand (the app also runs it by itself at 08:00 IST).
Run:  python cron_daily.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import automation, pipeline  # noqa: E402

if __name__ == "__main__":
    print(automation.run("manual"))
    print("Researching the queue now (Ctrl+C to stop)...")
    while True:
        r = pipeline.run_next()
        print(r)
        if r["state"] not in ("done", "failed"):
            break
