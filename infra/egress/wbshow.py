"""Guest WB prices in RUB, promo panel and raw volume/weight; no seller API."""
from browser import BATCH, SourceError, detail_url, fetch, number, opener, pause, price


def collect(page, nms, dest):
    prices, panels, vols, errors = {}, {}, {}, []
    template, headers = opener(page, nms, dest)
    for start in range(0, len(nms), BATCH):
        part = nms[start:start+BATCH]
        try:
            data = fetch(page, detail_url(template, part, dest), headers)
            for product in data['products']:
                nm = product['id']
                if nm not in part:
                    continue
                value = price(product)
                if value is None:
                    continue
                key = str(nm)
                prices[key] = value
                panel = product.get('panelPromoId')
                if panel is None or type(panel) is int:
                    panels[key] = panel
                volume, weight = product.get('volume'), product.get('weight')
                if number(volume) and (weight is None or number(weight)):
                    vols[key] = [volume, weight]
        except SourceError as exc:
            errors.append(str(exc))
            break
        if start+BATCH < len(nms):
            pause()
    missing = [n for n in nms if str(n) not in prices]
    if missing and not errors:
        errors.append('missing_products')
    return dict(prices=prices, panels=panels, vols=vols, errors=errors, missing=missing)
