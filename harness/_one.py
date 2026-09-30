"""Run a single harness job in its own process (used by --workers > 1).
Reads a JSON job from argv[1], prints one JSON result line prefixed
with RESULT: on stdout."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from harness.runner import run_one  # noqa: E402

job = json.loads(sys.argv[1])
r = run_one(job['sc'], job['seed'], dt=job['dt'], duration_s=job['duration'],
            frames_csv=job['frames_csv'])
print('RESULT:' + json.dumps(r), flush=True)
