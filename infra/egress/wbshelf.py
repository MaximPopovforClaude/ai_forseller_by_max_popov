"""First 100 WB recommendations for requested products, without account login."""
from urllib.parse import urlencode
from browser import BATCH, SourceError, detail_url, fetch, opener, pause, price


def card(p):
    v = price(p)
    return [p.get('name'), p.get('brand'), p.get('supplier'), p.get('supplierId'),
            p.get('subjectId'), p.get('reviewRating') or p.get('rating'),
            p.get('feedbacks'), v[1] if v else None]


def collect(page, nms, dest):
    shelves, cards, errors, meta = {}, {}, [], {}
    template, headers = opener(page, nms, dest)
    for start in range(0, len(nms), BATCH):
        part = nms[start:start+BATCH]
        try:
            j = fetch(page, detail_url(template, part, dest), headers)
            meta.update({p['id']: p for p in j['products'] if p['id'] in part})
        except SourceError as exc:
            errors.append(str(exc))
            return dict(shelves={}, cards={}, errors=errors, missing=nms)
        pause()
    for nm in nms:
        p = meta.get(nm)
        if not p or type(p.get('root')) is not int:
            continue
        params = dict(ab_testing='false', appType=1, curr='rub', dest=dest,
                      hide_vflags=4294967296, imt_id=p['root'], lang='ru', locale='ru',
                      nmId=nm, pSbjId=p.get('subjectParentId') or 0, page=1, query=nm,
                      resultset='catalog', sbjId=p.get('subjectId') or 0, sort='popular', spp=30)
        url = 'https://www.wildberries.ru/__internal/u-recom/recom/ru/common/v9/search?' + urlencode(params)
        try:
            j = fetch(page, url, headers)
            ps = j['products'][:100]
            total = j.get('total')
            if type(total) is not int or total < len(ps):
                raise SourceError('invalid_response')
            shelves[str(nm)] = [total, [q['id'] for q in ps]]
            cards[str(nm)] = card(p)
            cards.update({str(q['id']): card(q) for q in ps})
        except SourceError as exc:
            errors.append(str(exc))
            break
        pause()
    missing = [n for n in nms if str(n) not in shelves]
    if missing and not errors:
        errors.append('missing_products')
    return dict(shelves=shelves, cards=cards, errors=errors, missing=missing)
