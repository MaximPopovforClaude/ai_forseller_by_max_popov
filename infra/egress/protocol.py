"""Bounded protocol for the standalone WB browser worker; no account secrets."""
from datetime import datetime, timezone
import json
import re

VERSION = 1
MAX_INPUT = 65536
MAX_ITEMS = 300
DEFAULT_DEST = '-1257786'


def identifiers(values):
    if not isinstance(values, list) or len(values) > MAX_ITEMS:
        raise ValueError('invalid_items')
    if any(type(n) is not int or not 0 < n < 10**12 for n in values):
        raise ValueError('invalid_items')
    return list(dict.fromkeys(values))


def request(raw):
    if len(raw) > MAX_INPUT:
        raise ValueError('request_too_large')
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) - {'version', 'kind', 'nms', 'dest'}:
        raise ValueError('invalid_request')
    if type(obj.get('version')) is not int or obj['version'] != VERSION or obj.get('kind') not in ('probe', 'prices', 'shelves'):
        raise ValueError('invalid_request')
    obj['nms'] = identifiers(obj.get('nms', []))
    if obj['kind'] == 'probe' and obj['nms']:
        raise ValueError('invalid_request')
    obj['dest'] = obj.get('dest', DEFAULT_DEST)
    if not isinstance(obj['dest'], str) or not re.fullmatch(r'-?[0-9]{1,12}', obj['dest']):
        raise ValueError('invalid_destination')
    return obj


def result(kind, *, status='ok', **data):
    return dict(version=VERSION, kind=kind, status=status,
                captured_at=datetime.now(timezone.utc).isoformat(), **data)
