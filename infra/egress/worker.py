"""One bounded JSON job per process. Shared lock and deadline are in run.sh."""
import json
import os
import sys
from protocol import MAX_INPUT, request, result


def execute(job):
    if os.geteuid() == 0:
        raise RuntimeError('use_nonroot_user')
    if job['kind'] != 'probe' and not job['nms']:
        empty = dict(prices={}, panels={}, vols={}) if job['kind'] == 'prices' else dict(shelves={}, cards={})
        return result(job['kind'], dest=job['dest'], **empty, errors=[], missing=[])
    from playwright.sync_api import sync_playwright
    from browser import route
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, chromium_sandbox=True,
                                             args=['--disable-dev-shm-usage'])
        try:
            context = browser.new_context(locale='ru-RU', service_workers='block', accept_downloads=False)
            context.route('**/*', route)
            page = context.new_page()
            if job['kind'] == 'probe':
                page.set_content('<p>browser probe</p>')
                if page.evaluate('1+1') != 2:
                    raise RuntimeError('javascript_failed')
                return result('probe', chromium_sandbox=True, javascript=True,
                              browser_version=browser.version, errors=[])
            from wbshow import collect as prices
            from wbshelf import collect as shelves
            data = (prices if job['kind'] == 'prices' else shelves)(page, job['nms'], job['dest'])
            count = len(data.get('prices', data.get('shelves', {})))
            status = 'ok' if not data['errors'] else 'partial' if count else 'error'
            return result(job['kind'], status=status, dest=job['dest'], **data)
        finally:
            browser.close()


def main():
    kind = 'invalid'
    try:
        job = request(sys.stdin.buffer.read(MAX_INPUT+1))
        kind = job['kind']
        output = execute(job)
        encoded = json.dumps(output, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        from browser import SourceError
        code = str(exc) if isinstance(exc, (ValueError, SourceError)) else 'browser_runtime_failed'
        # Never emit exception messages from Chromium, SSH or a remote page.
        allowed = {'invalid_request', 'request_too_large', 'invalid_items', 'invalid_destination',
                   'unexpected_card_endpoint', 'unexpected_endpoint', 'invalid_response',
                   'card_unavailable_or_challenge'}
        if code not in allowed and not (code.startswith('http_') and code[5:].isdigit()):
            code = 'browser_runtime_failed' if isinstance(exc, RuntimeError) else 'invalid_request_or_runtime'
        if isinstance(exc, ModuleNotFoundError):
            code = 'playwright_missing'
        elif str(exc) == 'use_nonroot_user':
            code = 'use_nonroot_user'
        elif any(s in str(exc).lower() for s in ('no usable sandbox', 'operation not permitted', 'failed to move to new namespace')):
            code = 'browser_policy_denied'
        elif any(s in str(exc).lower() for s in ('missing x server', 'missing xserver', 'cannot open display')):
            code = 'display_unavailable'
        output = result(kind, status='error', errors=[code])
        encoded = json.dumps(output, ensure_ascii=False, allow_nan=False)
    print(encoded)
    return int(output['status'] == 'error')


if __name__ == '__main__':
    raise SystemExit(main())
