"""Audit source-only files without reading ignored local data or credentials."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|'
                    r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}|'
                    r'\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}|'
                    r'\bAKIA[A-Z0-9]{16}\b|'
                    r'postgres(?:ql)?://[^\s:@]+:[^\s@]+@')
FORBIDDEN = {'.env', 'credentials.json', 'auth.json', 'bridge.sqlite3'}
SKIP = {'.git', '.venv', 'node_modules', 'dist', '__pycache__', 'data'}


def candidates(root):
    if (root / '.git').exists():
        out = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode()
        return [root / p for p in out.split('\0') if p]
    return [p for p in root.rglob('*') if p.is_file() and not SKIP.intersection(p.relative_to(root).parts)]


def audit(root):
    errors = []
    files = candidates(root)
    for p in files:
        rel = p.relative_to(root)
        if p.is_symlink() or p.name in FORBIDDEN or p.name.endswith(('.dump', '.sqlite3', '.jsonl')) or {'data', '.ssh', '.codex', '.claude'}.intersection(rel.parts):
            errors.append(str(rel) + ': forbidden path or symlink')
            continue
        try:
            value = p.read_text()
        except UnicodeDecodeError:
            errors.append(str(rel) + ': binary source needs manual review')
            continue
        if SECRET.search(value):
            errors.append(str(rel) + ': possible secret (value not displayed)')
    return len(files), errors


if __name__ == '__main__':
    count, errors = audit(ROOT)
    print(f'Audited {count} source files; findings: {len(errors)}')
    for error in errors:
        print(error)
    sys.exit(bool(errors))
