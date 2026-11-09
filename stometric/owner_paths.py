"""Dedicated app Codex profile, separate from the owner's developer session."""
from pathlib import Path
import os
import shutil
import shlex

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/personal-ai'
PROFILE = BASE / 'codex'
JOBS = BASE / 'jobs'
CONTROL = BASE / 'control'
POLICY = ROOT / 'stometric/owner_policy.py'


def policy_command():
    return 'python3 ' + shlex.quote(str(POLICY))


def binary():
    candidates = [shutil.which('codex'), str(Path.home()/'.local/bin/codex')]
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p,os.X_OK)), None)


def environment():
    # CODEX_HOME is the native profile selector for this child process only.
    # Never copy the developer's login, API keys, hooks, apps or environment.
    return {'HOME':str(Path.home()), 'CODEX_HOME':str(PROFILE),
            'PATH':'/usr/local/bin:/usr/bin:/bin', 'LANG':'C.UTF-8'}
