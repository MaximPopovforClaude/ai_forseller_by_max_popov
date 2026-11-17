"""Short-lived successful Jam selectors, never exposed as completed daily data.

The scheduled collector holds collect:<shop>:jam_daily. Failed HTTP calls are
not retried here. A later scheduled pass may reuse its own validated successes
for the exact shop/day/catalog batch. Owner jobs retain their separate policy.
"""
import json

from . import jam


def open_progress(c, shop, day, nms):
                                                                               
                                                                            
    row=c.execute("SELECT to_regclass('jam_daily_progress') IS NOT NULL AS present").fetchone()
    return Progress(c,shop,day,nms) if row and row['present'] is True else None


class Progress:
    def __init__(self, c, shop, day, nms):
        self.c=c; self.shop=shop; self.day=day; self.nms=sorted(nms)
        if not 1 <= len(self.nms) <= 50 or len(set(self.nms)) != len(self.nms):
            raise ValueError('jam_progress_invalid_batch')

    def get(self, top, limit, nms):
        row=self.c.execute('''SELECT payload FROM jam_daily_progress
            WHERE account_id=%s AND day=%s AND nm_ids=%s::bigint[] AND top=%s
              AND max_limit=%s AND fetched_at >= now()-interval '48 hours' ''',
            (self.shop,self.day,self.nms,top,limit)).fetchone()
        if not row: return None
        payload=row['payload']
        from .jam_daily import FIELDS, number
        if not isinstance(payload,dict) or set(payload)-{str(n) for n in self.nms}:
            raise ValueError('jam_progress_invalid_payload')
                                                                             
                                                                          
        if not set(map(str,nms)).issubset(payload): return None
        out={nm:payload[str(nm)] for nm in nms}
        for queries in out.values():
            if not isinstance(queries,dict) or len(queries)>limit:
                raise ValueError('jam_progress_invalid_payload')
            for q,vals in queries.items():
                if (not isinstance(q,str) or not q.strip() or len(q.encode('utf-8'))>2000
                        or not isinstance(vals,list) or len(vals)!=len(FIELDS)
                        or any(v is not None and (type(v) not in (int,float) or number(v) is None) for v in vals)):
                    raise ValueError('jam_progress_invalid_payload')
        return out

    def effective_limit(self, default):
                                                                              
                                                             
        row=self.c.execute('''SELECT min(max_limit) AS lim FROM jam_daily_progress
            WHERE account_id=%s AND day=%s AND nm_ids=%s::bigint[]
              AND fetched_at >= now()-interval '48 hours' ''',
            (self.shop,self.day,self.nms)).fetchone()
        return min(default,row['lim']) if row and row['lim'] in (30,100) else default

    def put(self, top, limit, data):
        if top not in jam.TOPS or limit not in (30,100):
            raise ValueError('jam_progress_invalid_selector')
        if any(len(q)>limit for q in data.values()):
            raise ValueError('jam_progress_top_overflow')
                                                                                
        self.c.execute("DELETE FROM jam_daily_progress WHERE account_id=%s AND fetched_at < now()-interval '48 hours'",(self.shop,))
        self.c.execute('''INSERT INTO jam_daily_progress(account_id,day,nm_ids,top,max_limit,payload)
            VALUES(%s,%s,%s::bigint[],%s,%s,%s::jsonb)
            ON CONFLICT(account_id,day,nm_ids,top) DO UPDATE SET
              max_limit=EXCLUDED.max_limit,payload=EXCLUDED.payload,fetched_at=now()''',
            (self.shop,self.day,self.nms,top,limit,json.dumps(data,ensure_ascii=False)))
        self.c.commit()

    def finish(self):
        self.c.execute('DELETE FROM jam_daily_progress WHERE account_id=%s AND day=%s AND nm_ids=%s::bigint[]',
                       (self.shop,self.day,self.nms))
        self.c.commit()
