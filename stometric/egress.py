"""Standalone SSH transport. No private addresses, account keys or shell input."""
from datetime import datetime, timezone
from contextlib import suppress
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import warnings

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data/egress.json'
MAX_ITEMS = 300
MAX_OUTPUT = 32 * 1024 * 1024
TIMEOUT = 1900


class EgressError(RuntimeError):
    pass


def settings(value):
    fields = {'host', 'user', 'port', 'identity_file', 'known_hosts_file', 'remote_root', 'dest'}
    if not isinstance(value, dict) or set(value) != fields:
        raise EgressError('Invalid egress configuration fields')
    host = value['host']
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host):
        raise EgressError('Use an IPv4 address or DNS hostname without user, port or options')
    if host.replace('.', '').isdigit():
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            raise EgressError('Invalid IPv4 address') from None
    if (not isinstance(value['user'], str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', value['user'])
            or value['user'] == 'root'):
        raise EgressError('Use a dedicated non-root SSH user')
    if type(value['port']) is not int or not 1 <= value['port'] <= 65535:
        raise EgressError('Invalid SSH port')
    for key in ('identity_file', 'known_hosts_file', 'remote_root'):
        v = value[key]
        if not isinstance(v, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', v) or '..' in Path(v).parts:
            raise EgressError('Use absolute paths without spaces or shell characters')
    if not value['remote_root'].startswith(('/opt/', '/srv/')):
        raise EgressError('Worker must be installed under /opt or /srv')
    if not isinstance(value['dest'], str) or not re.fullmatch(r'-?[0-9]{1,12}', value['dest']):
        raise EgressError('Invalid WB destination')
    return dict(value)


def load_config():
    try:
        return settings(json.loads(CONFIG.read_text()))
    except FileNotFoundError:
        raise EgressError('Run scripts/configure_egress.py on your main server first') from None
    except (ValueError, OSError):
        raise EgressError('Cannot read valid data/egress.json') from None


def identifiers(values):
    if not isinstance(values, list) or len(values) > 100000:
        raise EgressError('Invalid product list')
    if any(type(n) is not int or not 0 < n < 10**12 for n in values):
        raise EgressError('Product IDs must be positive integers')
    return list(dict.fromkeys(values))


def ssh_command(cfg):
    cfg = settings(cfg)
    return ['ssh', '-F', '/dev/null', '-T', '-i', cfg['identity_file'],
            '-p', str(cfg['port']), '-l', cfg['user'],
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
            '-o', 'ConnectionAttempts=1', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
            '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no',
            '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none', '-o', 'LogLevel=ERROR',
            '-o', 'UserKnownHostsFile=' + cfg['known_hosts_file'],
            '-o', 'GlobalKnownHostsFile=/dev/null', '--', cfg['host'], cfg['remote_root'] + '/run.sh']


def exchange(command, payload):
    """Bound stdout while SSH runs. Its diagnostics never enter application logs."""
    with tempfile.TemporaryFile() as output:
        try:
            p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise EgressError('Cannot start OpenSSH client') from None
        try:
            p.stdin.write(payload)
            p.stdin.close()
            deadline = time.monotonic() + TIMEOUT
            while p.poll() is None:
                if os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                    raise EgressError('Worker output exceeded limit')
                if time.monotonic() > deadline:
                    raise EgressError('Worker timed out; check its status before another run')
                time.sleep(.1)
            if os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                raise EgressError('Worker output exceeded limit')
            output.seek(0)
            body = output.read(MAX_OUTPUT+1)
            if p.returncode == 75:
                raise EgressError('Worker busy; wait for the running browser job')
            if p.returncode in (124, 137):
                raise EgressError('Worker deadline reached; check the job before repeating')
            if p.returncode not in (0, 1):
                raise EgressError(f'SSH/worker failed (exit {p.returncode}); check host, lock and runtime')
            return body, p.returncode
        except (BrokenPipeError, OSError):
            raise EgressError('SSH transport failed') from None
        finally:
            if p.stdin and not p.stdin.closed:
                p.stdin.close()
            if p.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)
            p.wait()


def number(v, positive=False):
    return type(v) in (int, float) and math.isfinite(v) and (v > 0 if positive else v >= 0)


def id_map(obj):
    if not isinstance(obj, dict):
        raise EgressError('Invalid worker data')
    if any(not isinstance(k, str) or not re.fullmatch(r'[1-9][0-9]{0,11}', k) for k in obj):
        raise EgressError('Invalid product ID in response')
    return {int(k): v for k, v in obj.items()}


def validate(obj, kind, nms, dest):
    if not isinstance(obj, dict) or type(obj.get('version')) is not int or obj['version'] != 1 or obj.get('kind') != kind:
        raise EgressError('Wrong worker protocol or operation')
    if obj.get('status') not in ('ok', 'partial', 'error'):
        raise EgressError('Invalid worker status')
    try:
        stamp = datetime.fromisoformat(obj['captured_at'])
        if stamp.tzinfo is None:
            raise ValueError()
        age = (datetime.now(timezone.utc)-stamp).total_seconds()
        if not -300 <= age <= 3600:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise EgressError('Missing/stale worker timestamp; check both server clocks') from None
    errs = obj.get('errors')
    if not isinstance(errs, list) or len(errs) > 50 or any(not isinstance(e, str) or not re.fullmatch(r'[a-z0-9_]{1,80}', e) for e in errs):
        raise EgressError('Invalid worker errors')
    if obj['status'] == 'error':
        raise EgressError('Worker: ' + ', '.join(errs or ['failed']))
    if kind == 'probe':
        if obj.get('chromium_sandbox') is not True or obj.get('javascript') is not True:
            raise EgressError('Browser probe failed')
        return obj
    if obj.get('dest') != dest:
        raise EgressError('Worker region differs from requested destination')
    missing = obj.get('missing')
    if not isinstance(missing, list) or any(type(n) is not int for n in missing) or not set(missing) <= set(nms):
        raise EgressError('Invalid missing-product list')
    if kind == 'prices':
        prices = id_map(obj.get('prices'))
        panels, vols = id_map(obj.get('panels')), id_map(obj.get('vols'))
        if not set(prices) <= set(nms) or not set(panels) <= set(prices) or not set(vols) <= set(prices):
            raise EgressError('Unrequested product returned')
        if any(not isinstance(v, list) or len(v) != 2 or not number(v[0]) or not number(v[1], True) for v in prices.values()):
            raise EgressError('Invalid price; nothing saved')
        if any(v is not None and (type(v) is not int or v < 0) for v in panels.values()):
            raise EgressError('Invalid promo panel')
        if any(not isinstance(v, list) or len(v) != 2 or not number(v[0]) or (v[1] is not None and not number(v[1])) for v in vols.values()):
            raise EgressError('Invalid volume or weight')
        seen = set(prices)
    else:
        shelves, cards = id_map(obj.get('shelves')), id_map(obj.get('cards'))
        if not set(shelves) <= set(nms) or len(cards) > MAX_ITEMS*101:
            raise EgressError('Invalid shelf scope')
        linked = set(shelves)
        for v in shelves.values():
            if (not isinstance(v, list) or len(v) != 2 or type(v[0]) is not int
                    or not isinstance(v[1], list) or len(v[1]) > 100 or v[0] < len(v[1])
                    or any(type(x) is not int or not 0 < x < 10**12 for x in v[1])):
                raise EgressError('Invalid shelf')
            linked.update(v[1])
        if not set(cards) <= linked:
            raise EgressError('Unrelated shelf cards')
        for v in cards.values():
            if not isinstance(v, list) or len(v) != 8:
                raise EgressError('Invalid shelf card')
            if any(x is not None and (not isinstance(x, str) or len(x) > 2000) for x in v[:3]):
                raise EgressError('Invalid card text')
            if any(x is not None and (type(x) is not int or x < 0) for x in (v[3], v[4], v[6])):
                raise EgressError('Invalid card metadata')
            if (v[5] is not None and (not number(v[5]) or v[5] > 5)) or (v[7] is not None and not number(v[7], True)):
                raise EgressError('Invalid card rating or price')
        seen = set(shelves)
    if set(missing) != set(nms)-seen or (obj['status'] == 'ok' and (missing or errs)) or (obj['status'] == 'partial' and (not seen or not errs)):
        raise EgressError('Inconsistent worker coverage')
    return obj


def request(kind, nms, cfg=None):
    cfg = settings(cfg) if cfg is not None else load_config()
    nms = identifiers(nms)
    if kind not in ('probe', 'prices', 'shelves') or len(nms) > MAX_ITEMS or (kind == 'probe' and nms):
        raise EgressError('Invalid worker operation')
    data = dict(version=1, kind=kind, nms=nms, dest=cfg['dest'])
    body, code = exchange(ssh_command(cfg), json.dumps(data).encode())
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeError):
        raise EgressError('Worker did not return a JSON result') from None
    value = validate(obj, kind, nms, cfg['dest'])
    if code != 0:
        raise EgressError('Worker exit status contradicts its response')
    blocking = [e for e in value['errors'] if e != 'missing_products']
    if blocking:
        raise EgressError('Worker stopped: ' + ', '.join(blocking))
    return value


def fetch_prices(nms):
    nms = identifiers(nms)
    prices, panels, vols = {}, {}, {}
    for start in range(0, len(nms), MAX_ITEMS):
        obj = request('prices', nms[start:start+MAX_ITEMS])
        prices.update({k: tuple(v) for k, v in id_map(obj['prices']).items()})
        panels.update(id_map(obj['panels']))
        vols.update({k: (v[0] / 10, v[1]) for k, v in id_map(obj['vols']).items()})
        if obj['errors']:
            warnings.warn('WB prices incomplete: ' + ', '.join(obj['errors']), RuntimeWarning)
    return prices, panels, vols


def fetch_shelves(nms):
    return request('shelves', identifiers(nms))
