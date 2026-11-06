"""Read-only guest browser. Refusals stop a request; there is no CAPTCHA solver."""
import json
import math
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

BATCH = 100
PAUSE = 2
MAX_BODY = 8 * 1024 * 1024
STOP_HTTP = {401, 403, 429, 498}
HOSTS = ('wildberries.ru', 'wb.ru', 'wbbasket.ru', 'wbstatic.net')
DETAIL = '/__internal/u-card/cards/v4/detail'
FETCH = '''async ([url, headers, limit]) => {
  const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), 30000);
  try {
    const r = await fetch(url, {method:'GET', credentials:'include', headers,
                              redirect:'error', signal:ctl.signal});
    if (r.status !== 200) return [r.status, ''];
    const reader = r.body.getReader(); let n=0, chunks=[];
    for (;;) { const {done,value} = await reader.read(); if(done) break;
      n += value.byteLength; if(n>limit) { await reader.cancel(); return [0,'']; }
      chunks.push(value); }
    let all=new Uint8Array(n), at=0; for(const c of chunks){all.set(c,at);at+=c.length;}
    return [200, new TextDecoder().decode(all)];
  } finally { clearTimeout(timer); }
}'''


class SourceError(Exception):
    pass


def allowed(url):
    try:
        u = urlsplit(url)
        return (u.scheme == 'https' and u.port in (None, 443) and not u.username
                and any(u.hostname == h or (u.hostname or '').endswith('.' + h) for h in HOSTS))
    except ValueError:
        return False


def route(request_route):
    r = request_route.request
    if r.method in ('GET', 'HEAD') and allowed(r.url):
        request_route.continue_()
    else:
        request_route.abort()


def detail_url(url, nms, dest):
    u = urlsplit(url)
    if u.scheme != 'https' or u.netloc != 'www.wildberries.ru' or u.path != DETAIL:
        raise SourceError('unexpected_card_endpoint')
    query = parse_qs(u.query, keep_blank_values=True)
    query.update(nm=[';'.join(map(str, nms))], dest=[dest])
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(query, doseq=True), ''))


def products(body):
    if not isinstance(body, str) or len(body.encode()) > MAX_BODY:
        raise SourceError('invalid_response')
    try:
        obj = json.loads(body)
    except ValueError:
        raise SourceError('invalid_response') from None
    if not isinstance(obj, dict) or not isinstance(obj.get('products'), list):
        raise SourceError('invalid_response')
    if any(not isinstance(p, dict) or type(p.get('id')) is not int for p in obj['products']):
        raise SourceError('invalid_response')
    return obj


def fetch(page, url, headers):
    if not allowed(url) or urlsplit(url).netloc != 'www.wildberries.ru':
        raise SourceError('unexpected_endpoint')
    status, body = page.evaluate(FETCH, [url, headers, MAX_BODY])
    if status != 200:
        raise SourceError(f'http_{status}' if type(status) is int else 'invalid_response')
    return products(body)


def opener(page, nms, dest):
    seen = []
    def capture(r):
        u = urlsplit(r.url)
        if u.scheme == 'https' and u.netloc == 'www.wildberries.ru' and u.path == DETAIL:
            seen.append(r)
    page.on('request', capture)
    try:
        for nm in nms[:3]:
            response = page.goto(f'https://www.wildberries.ru/catalog/{nm}/detail.aspx',
                                 wait_until='domcontentloaded', timeout=60000)
            if response and response.status in STOP_HTTP:
                raise SourceError(f'http_{response.status}')
            for _ in range(15):
                if seen:
                    r = seen[-1]
                    # Headers stay in this disposable guest context. Never return/log them.
                    headers = {k: v for k, v in r.all_headers().items()
                               if k.lower() not in ('cookie', 'authorization', 'user-agent',
                                                    'referer', 'accept-encoding', 'host')
                               and not k.startswith(':')}
                    return detail_url(r.url, nms[:BATCH], dest), headers
                page.wait_for_timeout(1000)
        raise SourceError('card_unavailable_or_challenge')
    finally:
        page.remove_listener('request', capture)


def number(value, *, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def price(product):
    best = None
    for size in product.get('sizes') or []:
        if not isinstance(size, dict):
            continue
        p = size.get('price') or {}
        if not isinstance(p, dict) or not number(p.get('basic')) or not number(p.get('product'), positive=True):
            continue
        value = [p['basic'] / 100, p['product'] / 100]
        if best is None or value[1] < best[1]:
            best = value
    return best


def pause():
    time.sleep(PAUSE)
