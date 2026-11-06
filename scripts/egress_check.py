"""Explicit read-only probe. Does not write prices, run AI or enable timers."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stometric.egress import EgressError, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('probe', 'prices', 'shelves'))
    parser.add_argument('nms', nargs='*', type=int)
    args = parser.parse_args()
    if (args.kind == 'probe' and args.nms) or (args.kind != 'probe' and not args.nms):
        parser.error('probe takes no IDs; prices/shelves require your product IDs')
    try:
        obj = request(args.kind, args.nms)
        fields = ('version', 'kind', 'status', 'captured_at', 'dest', 'errors', 'missing',
                  'chromium_sandbox', 'javascript', 'browser_version')
        summary = {k: obj[k] for k in fields if k in obj}
        summary['prices'] = obj.get('prices', {})
        summary['shelves_count'] = len(obj.get('shelves', {}))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return int(obj['status'] != 'ok')
    except EgressError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
