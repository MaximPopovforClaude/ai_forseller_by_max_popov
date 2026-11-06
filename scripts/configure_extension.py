"""Point the unpacked Chrome extension at this installation only."""
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
origin = sys.argv[1].rstrip('/')
u = urlsplit(origin)
if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
    raise SystemExit('Expected an HTTPS origin')
manifest = root / 'extension/manifest.json'
value = json.loads(manifest.read_text())
value['host_permissions'] = [origin + '/*', 'https://*.wildberries.ru/*']
manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
bg = root / 'extension/bg.js'
text, count = re.subn(r'^const API = .*?;', 'const API = ' + json.dumps(origin) + ';', bg.read_text(), count=1, flags=re.M)
if count != 1:
    raise SystemExit('Extension origin declaration not found')
bg.write_text(text)
print('Extension configured for this installation. Reload it in Chrome.')
