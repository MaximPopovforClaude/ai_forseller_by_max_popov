"""Comparable order amounts from posting prices, never from realized subsidies."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

SELLER_LABEL = "Сумма заказов с учетом скидки продавца (отправления), руб"
CUSTOMER_LABEL = "Сумма заказов с учетом скидки продавца и соинвеста Ozon, руб"
COVERAGE_LABEL = "Полнота цен покупателей в загруженных отправлениях, %"
NOTE = ("Суммы до и после соинвеста сравниваются по отправлениям FBO/FBS, по дате заказа МСК, включая отменённые. "
        "После соинвеста — цена покупателя из заказа Ozon со всеми переданными скидками. "
        "При неполных ценах, неизвестной валюте или валюте не RUB сумма не показана; полнота считается по количеству товаров в загруженных отправлениях. "
        "Сумма из аналитики Ozon может отличаться по составу заказов и срокам обновления.")
KEYS = ("order_seller_sum", "order_customer_sum", "order_price_coverage")


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def customer_price(row):
    """Match by SKU (legacy product_id), not by item position. RUB only."""
    items = row.get("financial_products")
    if not isinstance(items, list):
        return None
    sku = str(row["sku"])
    matches = [it for it in items if isinstance(it, dict)
               and str(it.get("sku") if it.get("sku") is not None else it.get("product_id")) == sku]
    if len(matches) != 1:
        return None
    item = matches[0]
    
    if item.get("quantity") is not None and number(item["quantity"]) != number(row["qty"]):
        return None
    price = item.get("customer_price")
    currency = item.get("customer_currency_code")
    if isinstance(price, dict):
        own_currency = price.get("currency")
        if currency and own_currency and currency != own_currency:
            return None
        currency = own_currency or currency
        price = price.get("amount")
    if currency != "RUB":
        return None
    return number(price)


def daily(rows, skus=None):
    """Preserve unknown prices as unknown; include cancellations like the dashboard."""
    result = defaultdict(lambda: dict(qty=Decimal(0), known=Decimal(0), customer=Decimal(0), seller=Decimal(0)))
    selected = set(skus) if skus is not None else None
    for row in rows:
        if selected is not None and row["sku"] not in selected:
            continue
        qty = number(row.get("qty"))
        if not qty:
            continue
        v = result[row["order_day"]]
        v["qty"] += qty
        v["seller"] += qty * (number(row.get("price")) or Decimal(0))
        price = customer_price(row)
        if price is not None:
            v["known"] += qty
            v["customer"] += qty * price
    return dict(result)


def load_daily(c, shop, start, end, skus=None):
    
    rows = c.execute("""SELECT order_day, sku, qty, price,
                               raw#>'{financial_data,products}' AS financial_products
                        FROM oz_postings WHERE account_id=%s AND order_day BETWEEN %s AND %s""",
                     (shop, start, end))
    return daily(rows, skus)


def period(days, start, end):
    values = [v for d, v in days.items() if start <= d <= end]
    qty = sum((v["qty"] for v in values), Decimal(0))
    known = sum((v["known"] for v in values), Decimal(0))
    return {"order_seller_sum": float(sum((v["seller"] for v in values), Decimal(0))) if qty else None,
            "order_customer_sum": float(sum((v["customer"] for v in values), Decimal(0))) if qty and known == qty else None,
            "order_price_coverage": float(known / qty) if qty else None}
