"""Initialize local secrets interactively, without displaying or overwriting them."""
import getpass
import os
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1]
site = input('HTTPS address of your installation: ').strip().rstrip('/')
u = urlsplit(site)
if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path:
    raise SystemExit('Use an HTTPS origin, for example https://analytics.example.org')
dsn = getpass.getpass('PostgreSQL DSN (hidden; empty = local peer authentication): ').strip() or 'postgresql:///seller_analytics'
if any(ch in dsn + site for ch in '\r\n'):
    raise SystemExit('Newlines are not allowed')
fd = os.open(root / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(f'DATABASE_URL={dsn}\nSITE_URL={site}\nAIS_MASTER_KEY={Fernet.generate_key().decode()}\n')
(root / 'data').mkdir(mode=0o700, exist_ok=True)
print('Local configuration created. Back it up securely; no secrets were printed.')
