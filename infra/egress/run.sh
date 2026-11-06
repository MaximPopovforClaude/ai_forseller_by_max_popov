#!/bin/sh
# Fixed command for the dedicated SSH key. Both kinds share this lock.
set -eu
umask 077
EGRESS_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$EGRESS_ROOT"
export PLAYWRIGHT_BROWSERS_PATH="$EGRESS_ROOT/browsers"
exec /usr/bin/flock -E 75 -w 60 "$EGRESS_ROOT/state/browser.lock" \
    /usr/bin/timeout --kill-after=10 1800 \
    /usr/bin/xvfb-run -a "$EGRESS_ROOT/.venv/bin/python" -I "$EGRESS_ROOT/entry.py"
