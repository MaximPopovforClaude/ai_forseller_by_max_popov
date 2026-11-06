#!/bin/sh
# Run on the NEW Russian server only. Does not install SSH keys or start timers.
set -eu
if [ "${1:-}" = "--plan" ]; then
    echo 'Install dedicated seller-egress user; root-owned /opt/seller-egress; Python/Playwright/Chromium, Xvfb; no keys/timers/firewall changes.'
    exit 0
fi
if [ "${1:-}" != "--install" ] || [ "$(id -u)" -ne 0 ]; then
    echo 'Review first: sh setup.sh --plan; then sudo sh setup.sh --install on the Russian VPS.' >&2
    exit 2
fi
EGRESS_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
EGRESS_TARGET=/opt/seller-egress
if [ -e "$EGRESS_TARGET" ]; then
    echo 'Target exists; preserve it and follow README update steps.' >&2
    exit 2
fi
if id seller-egress >/dev/null 2>&1; then
    echo 'User seller-egress already exists; administrator must review it before installation.' >&2
    exit 2
fi
apt-get update
apt-get install -y python3-venv xvfb xauth util-linux coreutils openssh-server
useradd --create-home --user-group --shell /bin/sh seller-egress
install -d -m 0755 "$EGRESS_TARGET"
for EGRESS_FILE in browser.py protocol.py wbshow.py wbshelf.py worker.py entry.py requirements.txt; do
    install -m 0644 "$EGRESS_SOURCE/$EGRESS_FILE" "$EGRESS_TARGET/$EGRESS_FILE"
done
install -m 0755 "$EGRESS_SOURCE/run.sh" "$EGRESS_TARGET/run.sh"
install -d -m 0700 -o seller-egress -g seller-egress "$EGRESS_TARGET/state"
python3 -m venv "$EGRESS_TARGET/.venv"
"$EGRESS_TARGET/.venv/bin/pip" install -r "$EGRESS_TARGET/requirements.txt"
PLAYWRIGHT_BROWSERS_PATH="$EGRESS_TARGET/browsers" "$EGRESS_TARGET/.venv/bin/playwright" install --with-deps chromium
chmod -R a+rX "$EGRESS_TARGET/browsers"
echo 'Installed. Review SSH access, then run the sandbox probe from README before any WB request.'
