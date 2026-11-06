"""Explicit local opt-in to paid daily API analysis after source checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stometric.web
from stometric import db, ai_routing, kit_analytics
from stometric.config import today_msk
from stometric.private_ai import scheduled_ai
from datetime import timedelta

shop = int(input('Shop ID to enable for paid daily analysis: '))
with db.connect() as c:
    row = c.execute("SELECT id,title,marketplace FROM accounts WHERE id=%s AND is_active", (shop,)).fetchone()
    if not row or row['marketplace'] not in ('wb', 'ozon'):
        raise SystemExit('Shop not found or unsupported')
    with scheduled_ai(c):
        if not ai_routing.shop_route(c, shop)['ai_ready']:
            raise SystemExit('Configure a workspace API key first')
    coverage = kit_analytics.source_coverage(c, shop, row['marketplace'], today_msk() - timedelta(days=1))
    if not coverage['ready']:
        print(coverage.get('warnings', []))
        raise SystemExit('Sources incomplete; no opt-in saved')
    if input('Paid API calls will run daily for this shop. Type ENABLE to continue: ') != 'ENABLE':
        raise SystemExit('No changes')
    c.execute('INSERT INTO ai_task_shops(account_id,enabled) VALUES (%s,true) ON CONFLICT (account_id) DO UPDATE SET enabled=true', (shop,))
    c.execute("INSERT INTO audit_log(workspace_id,action,details) SELECT workspace_id,'installation/enable-tasks',jsonb_build_object('shop',id) FROM accounts WHERE id=%s", (shop,))
print('Opt-in saved; start the timer separately when ready.')
