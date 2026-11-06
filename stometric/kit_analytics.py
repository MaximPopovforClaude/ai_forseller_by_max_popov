"""Source completeness shared by reports and tasks; no personal bridge."""
from datetime import timedelta
import hashlib
import json
from . import entry_coverage


def source_coverage(c, shop, marketplace, source_day):
    if marketplace == 'ozon':
        from .ozon_task_data import coverage
        return coverage(c, shop, source_day)
    if marketplace != 'wb':
        return {'ready': False, 'unsupported': True, 'warnings': ['Площадка не поддерживается.']}
    start = source_day - timedelta(days=7)
    expected = [start + timedelta(days=i) for i in range(8)]
    present = entry_coverage.daily_days(c, [shop], start, source_day).get(shop, set())
    missing = [d.isoformat() for d in expected if d not in present]
    reports = c.execute('''SELECT r.id,r.d_from,r.uploaded_at FROM entry_reports r
        WHERE r.account_id=%s AND r.d_from=r.d_to AND r.d_from BETWEEN %s AND %s
        AND EXISTS (SELECT 1 FROM entry_rows e WHERE e.report_id=r.id) ORDER BY r.d_from,r.id''',
                        (shop, start, source_day)).fetchall()
    latest = max((r['uploaded_at'] for r in reports if r.get('uploaded_at')), default=None)
    fingerprint = hashlib.sha256(json.dumps([dict(r) for r in reports], default=str, sort_keys=True).encode()).hexdigest()
    return {'marketplace': 'wb', 'from': start.isoformat(), 'day': source_day.isoformat(),
            'required_days': [d.isoformat() for d in expected], 'present_days': sorted(d.isoformat() for d in present),
            'missing_days': missing, 'ready': not missing, 'latest_uploaded_at': str(latest) if latest else None,
            'fingerprint': fingerprint, 'warnings': ['Нет точек входа: ' + ', '.join(missing)] if missing else []}
