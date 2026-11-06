"""Install user units. Does not start services or edit system configuration."""
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if any(ch in str(root) for ch in ' \n\r%"'):
    raise SystemExit('Use an installation path without spaces or systemd specifiers')
units = Path.home() / '.config/systemd/user'
units.mkdir(parents=True, exist_ok=True)
python = root / '.venv/bin/python'
specs = {
    'web': (f'{root}/.venv/bin/uvicorn stometric.web:app --host 127.0.0.1 --port 8100 --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1', False),
    'collect': (f'{python} -m stometric collect-due', True),
    'onboard@': (f'{python} -m stometric first-load %i', True),
    'precompute': (f'{python} -m stometric precompute', True),
    'bots': (f'{python} -m stometric.bots', False),
    'aitasks': (f'{python} tools/ai_tasks/run.py', True),
    'showcase': (f'{python} -m stometric.showcase', True),
    'shelves': (f'{python} -m stometric.shelves', True),
}
for name, (command, once) in specs.items():
    text = f'[Unit]\nDescription=Seller Analytics {name}\nAfter=network-online.target\n\n[Service]\nWorkingDirectory={root}\nEnvironment=PYTHONPATH={root}\nExecStart={command}\n'
    text += 'Type=oneshot\nTimeoutStartSec=6h\n' if once else 'Restart=on-failure\nRestartSec=10\n'
    text += '\n[Install]\nWantedBy=default.target\n'
    (units / f'ai-stometric-{name}.service').write_text(text)
for name, when in {'collect': '*:0/10', 'aitasks': '*:0/10', 'precompute': '*-*-* 03:30:00 UTC',
                   'showcase': '*:0/30', 'shelves': '*-*-* 23:00:00 UTC'}.items():
    (units / f'ai-stometric-{name}.timer').write_text(f'[Unit]\nDescription=Seller Analytics {name}\n\n[Timer]\nOnCalendar={when}\nPersistent=false\n\n[Install]\nWantedBy=timers.target\n')
print('Units installed. Review them, then run systemctl --user daemon-reload. No services were started.')
