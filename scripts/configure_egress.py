"""Write non-secret connection parameters on a NEW main server; no network."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stometric.egress import CONFIG, settings


def main():
    if CONFIG.exists():
        raise SystemExit('data/egress.json exists. Review it locally; no overwrite performed.')
    def ask(label, default=''):
        return input(label + (f' [{default}]' if default else '') + ': ').strip() or default
    cfg = settings(dict(
        host=ask('Russian VPS IPv4 or hostname'), user=ask('Dedicated SSH user', 'seller-egress'),
        port=int(ask('SSH port', '22')),
        identity_file=str(Path(ask('Path to your SSH private key (not its contents)')).expanduser()),
        known_hosts_file=str(Path(ask('Path to verified known_hosts file')).expanduser()),
        remote_root=ask('Worker directory', '/opt/seller-egress'), dest=ask('WB destination', '-1257786')))
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(cfg, f, indent=2)
        f.write('\n')
    print('Saved non-secret paths/settings in data/egress.json. No connection or schedule started.')


if __name__ == '__main__':
    main()
