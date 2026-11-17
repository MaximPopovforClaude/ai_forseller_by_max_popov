"""Readable AI prose only: never alter saved evidence, identifiers or action values."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext


WRITING_RULES = """Текст для владельца магазина:
- Пиши простыми короткими предложениями: вывод → 1–2 главные цифры → конкретное действие и условие проверки.
  Не превращай объяснение в перечень исходных данных. Обычно why — 2–3 предложения, steps — 1–3 коротких шага.
- Деньги в тексте округляй до целых рублей, проценты и коэффициенты — максимум до одного знака после запятой.
  Разделяй тысячи пробелами. Очень маленькое ненулевое значение не превращай в ноль: «меньше 0,1 %».
  Для строгой проверки чисел не заменяй 12540 на «12,5 тыс.» и не округляй до тысяч.
- Сначала указывай готовый результат: «Порог расходов на рекламный заказ — около 2 524 ₽; вчера было 501 ₽».
  Это пример формы, не данные магазина. Бери итоговый порог из расчёта кода в досье/JSON.
  Не заставляй читателя перемножать длинные дроби; не выводи цепочки формул в why/steps.
  Если готового результата нет, не выдумывай его и не заменяй результат непосчитанной формулой.
- Расчёты, сравнения с порогами и рекомендации основаны на исходной точности, округляется только пояснение.
  В частности, сначала посчитать произведение исходных значений, потом округлить итог, не множители.
- Вместо CPO пиши «стоимость заказа из рекламы», вместо длинного описания причинности — «связь пока не доказана».
  Сохраняй смысл, период, источник, ограничения, отрицания и условия остановки. Совпадение не доказывает причину.
- Артикулы продавца, SKU/nm_id, номера кампаний, даты, поисковые фразы, ссылки и названия сохраняй точно.
  Конкретные цены и ставки, которые предлагаешь ввести, сохраняй с нужной точностью, чтобы текст совпадал с параметрами действия.
  В JSON поля effect_week, check/target, params, идентификаторы и остальные машинные значения не округляй ради текста.
"""

_SPACE = r"[ \u00a0\u202f]"
_NUM = rf"[-−+]?\d{{1,15}}(?:{_SPACE}\d{{3}})*(?:[.,]\d{{1,18}})?"
_PRODUCT = re.compile(
    rf"(?<!\w)(?:порог рекламы на заказ|порог расходов на рекламный заказ|безубыточная реклама на заказ|безубыточный CPO|порог CPO)"
    rf"\s*(?:—|–|:|=|-)\s*(?P<a>{_NUM})\s*(?P<pct>%)?\s*[×хx*]\s*(?P<b>{_NUM})\s*(?P<u>₽|руб(?:\.|лей)?)"
    r"(?![\w]|\s*[×хx*/+=−-])", re.IGNORECASE)
_UNIT = re.compile(rf"(?<![\w.,/])(?P<n>{_NUM})\s*(?P<u>₽|руб(?:\.|лей)?|%)(?!\w)")
_PROTECTED = re.compile(r"```[\s\S]*?```|`[^`\n]*`|https?://[^\s<>]+|«[^»\n]*»|\"[^\"\n]*\"")


def _decimal(value):
    return Decimal(re.sub(r"[ \u00a0\u202f]", "", str(value)).replace(",", ".").replace("−", "-"))


def _formatted(value, unit):
    places = 1 if unit == "%" else (2 if 0 < abs(value) < 1 else 0)
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if value and not rounded:
        return ("<" if value > 0 else ">−") + str(quantum).replace(".", ",") + " " + unit
    number = format(rounded, f",.{places}f").replace(",", " ").replace(".", ",")
    if places:
        number = number.rstrip("0").rstrip(",")
    return number + " " + unit


def display_text(text, protected=(), *, round_values=True):
    """Format a response copy, not stored prose or numeric action fields.

    Only explicitly labelled two-factor monetary thresholds are evaluated.
    Other expressions, unitless decimals, quoted phrases and identifiers stay intact.
    """
    if not isinstance(text, str) or not text:
        return text
    patterns = [_PROTECTED.pattern] + [re.escape(str(v)) for v in protected if v is not None and str(v)]
    guard = re.compile("|".join(patterns))

    def prose(chunk):
        def product(m):
            try:
                with localcontext() as ctx:
                    ctx.prec = 80
                    a, b = _decimal(m['a']), _decimal(m['b'])
                    if m['pct']:
                        a /= 100
                                                                                 
                    if not 0 <= a <= 1 or abs(b) > Decimal('1e12'):
                        return m[0]
                    result = _formatted(a * b, '₽')
                    return ('Порог расходов на рекламный заказ — ' + ('' if result.startswith(('<', '>')) else 'около ')
                            + result + ('.' if m['u'].endswith('.') else ''))
            except InvalidOperation:
                return m[0]

        chunk = _PRODUCT.sub(product, chunk)
        if not round_values:
            return chunk

        def unit(m):
                                                                                    
            if not re.search(r'[.,]', m['n']):
                return m[0]
            try:
                with localcontext() as ctx:
                    ctx.prec = 80
                    value = _decimal(m['n'])
                    result = _formatted(value, '%' if m['u'] == '%' else '₽')
                                                                                    
                                                                             
                    already = re.search(r'(?:около|примерно|≈|~)\s*$', chunk[:m.start()], re.I)
                    shown = result.split(' ')[0] if result.startswith(('<', '>')) else result.rsplit(' ', 1)[0]
                    changed = result.startswith(('<', '>')) or _decimal(shown) != value
                    return (('' if already or not changed or result.startswith(('<', '>')) else '≈ ') + result
                            + ('.' if m['u'].endswith('.') else ''))
            except InvalidOperation:
                return m[0]

        return _UNIT.sub(unit, chunk)

    out, start = [], 0
    for m in guard.finditer(text):
        out.extend((prose(text[start:m.start()]), m[0]))
        start = m.end()
    out.append(prose(text[start:]))
    return ''.join(out)


def unit_ad_threshold(unit):
    """Existing unit model: buyout share × profit per bought unit, before ads.

    Used only to supply an already calculated number to the writer/number validator.
    Missing cost/economics never becomes a zero threshold.
    """
    try:
        if not unit.get('cost') or unit.get('bp') is None or unit.get('profit') is None:
            return None
        bp, profit = Decimal(str(unit['bp'])), Decimal(str(unit['profit']))
        if not bp.is_finite() or not profit.is_finite() or not 0 < bp <= 1:
            return None
        return float(bp * profit)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
