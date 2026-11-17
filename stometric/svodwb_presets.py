"""Personal named summary layouts; values and calendar dates are never stored."""
from .sheets.svodwb import PERIODS, metric_options


def normalize(value):
    if not isinstance(value, dict) or set(value) != {'items'} or not isinstance(value['items'], list) or len(value['items']) > 30:
        raise ValueError('Можно сохранить не более 30 пресетов')
    allowed = set(metric_options())
    result, names = [], set()
    for item in value['items']:
        if not isinstance(item, dict) or set(item) != {'name', 'cols', 'hidden'}:
            raise ValueError('Неверный формат пресета')
        name = item['name'].strip() if isinstance(item['name'], str) else ''
        if not name or len(name) > 80 or name.casefold() in names:
            raise ValueError('Нужно уникальное название пресета, до 80 символов')
        names.add(name.casefold())
        out = {'name': name}
        for key in ('cols', 'hidden'):
            rows = item[key]
            if not isinstance(rows, list) or len(rows) > 200 or (key == 'cols' and not rows):
                raise ValueError('В пресете должно быть от 1 до 200 видимых колонок')
            clean = []
            for row in rows:
                if not isinstance(row, list) or len(row) not in ((3,) if key == 'cols' else (3, 4)):
                    raise ValueError('Неверный формат колонки')
                g, m, p = row[:3]
                if not all(isinstance(x, str) for x in (g, m, p)) or len(g) > 120 or m not in allowed:
                    raise ValueError('Неизвестный показатель или слишком длинная группа')
                if m != 'разница' and p not in PERIODS:
                    raise ValueError('Неизвестный период')
                clean.append([g, m, '' if m == 'разница' else p])
                if len(row) == 4:
                    if type(row[3]) is not int or not 0 <= row[3] <= 400:
                        raise ValueError('Неверное место скрытой колонки')
                    clean[-1].append(row[3])
            out[key] = clean
        result.append(out)
    return {'items': result}
