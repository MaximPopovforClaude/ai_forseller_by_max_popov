"""Human balance workspace. Company/common data requires unrestricted membership."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import balance as b, balance_excel, balance_sources, tabcache
from .config import today_msk
from .web import conn,current_user,_audit

router=APIRouter()


def valid_day(day):
    if day>today_msk() or day<date(2024,1,1): raise HTTPException(400,'Выберите дату с 2024 года не позднее сегодня')


class CompanyIn(BaseModel):
    title: str=Field(min_length=1,max_length=200)
    shops: list[int]=Field(min_length=1,max_length=100)


class BatchIn(BaseModel):
    kind: Literal['stock','assets','settlement']
    label: str=Field(min_length=1,max_length=100)
    day: date
    payload: dict
    request_key: UUID
    shop_id: int|None=None
    previous_id: int|None=None


@router.get('/api/workspaces/{ws}/balance/report')
def report(ws:int,day:date,shops:str,u=Depends(current_user),c=Depends(conn)):
    valid_day(day);ctx=b.scope(c,u,ws)
    try: ids=sorted(set(int(x) for x in shops.split(',') if x))
    except ValueError:raise HTTPException(400,'Неверный список магазинов') from None
    if not ids or len(ids)>16 or not set(ids)<=ctx['ids']:raise HTTPException(400,'Выберите от 1 до 16 доступных магазинов')
    comps=b.companies(c,ws,ctx)
    data={}; errors={}
    for s in ctx['shops']:
        if s['id'] not in ids:continue
        try:
            data[s['id']]=tabcache.get(c,s['id'],'company_balance_inventory',balance_sources.cache_params(day),
                lambda cc,shop=s['id'],mp=s['marketplace']:balance_sources.inventory(cc,shop,mp,day))
        except Exception:
            c.rollback()
            errors[s['id']]='Остатки не удалось подготовить. Повторите чтение позже'
    cb={comp['id']:b.latest_batches(c,comp['id'],day) for comp in comps if set(comp['shops']) & set(ids)}
    result={k:b.report_projection(ids,data,comps,cb,ex) for k,ex in [('with_fbs',False),('without_fbs',True)]}
                                                                                             
    return jsonable_encoder({'day':day,'shops':{k:{n:v for n,v in d.items() if n!='rows'} for k,d in data.items()},
        'errors':errors,'variants':result,'companies':[
            {'company':comp,'batches':[x for x in cb.get(comp['id'],[]) if x['kind']=='settlement' and x['shop_id'] in ids
                or x['kind']!='settlement' and set(comp['shops'])<=set(ids)]}
            for comp in comps if set(comp['shops']) & set(ids)]})


@router.get('/api/workspaces/{ws}/balance')
def meta(ws:int,u=Depends(current_user),c=Depends(conn)):
    ctx=b.scope(c,u,ws)
    return jsonable_encoder({'companies':b.companies(c,ws,ctx),'shops':ctx['shops'],'can_edit':ctx['write'],
                             'common_access':ctx['full'],'today':today_msk(),'categories':balance_excel.CATEGORIES})


@router.post('/api/workspaces/{ws}/balance/companies')
def create(ws:int,body:CompanyIn,u=Depends(current_user),c=Depends(conn)):
    try: ident=b.save_company(c,u,ws,body.title,body.shops)
    except ValueError as e: raise HTTPException(400,str(e)) from None
    _audit(c,u,ws,'balance/company',{'id':ident,'shops':body.shops});c.commit()
    return {'id':ident}


@router.get('/api/workspaces/{ws}/balance/shops/{shop}')
def shop_view(ws:int,shop:int,day:date,u=Depends(current_user),c=Depends(conn)):
    valid_day(day);ctx=b.scope(c,u,ws)
    s=next((s for s in ctx['shops'] if s['id']==shop),None)
    if not s: raise HTTPException(404,'Магазин недоступен')
    data=tabcache.get(c,shop,'company_balance_inventory',balance_sources.cache_params(day),
        lambda cc:balance_sources.inventory(cc,shop,s['marketplace'],day))
    return jsonable_encoder(data)


@router.get('/api/workspaces/{ws}/balance/companies/{ident}')
def company_view(ws:int,ident:int,day:date,u=Depends(current_user),c=Depends(conn)):
    valid_day(day);ctx,comp=b.company(c,u,ws,ident)
    batches=b.latest_batches(c,ident,day)
    return jsonable_encoder({'company':comp,'batches':batches,'can_edit':ctx['write']})


@router.get('/api/workspaces/{ws}/balance/companies/{ident}/history')
def history(ws:int,ident:int,u=Depends(current_user),c=Depends(conn)):
    b.company(c,u,ws,ident)
    rows=c.execute('''SELECT id,kind,label,shop_id,day,created_at,created_by FROM balance_batches
        WHERE company_id=%s ORDER BY id DESC LIMIT 201''',(ident,)).fetchall()
    return jsonable_encoder({'rows':rows[:200],'more':len(rows)>200})


@router.get('/api/workspaces/{ws}/balance/companies/{ident}/batches/{batch}')
def batch_view(ws:int,ident:int,batch:int,u=Depends(current_user),c=Depends(conn)):
    b.company(c,u,ws,ident)
    row=c.execute('SELECT id,kind,label,shop_id,day,payload,created_at FROM balance_batches WHERE company_id=%s AND id=%s',(ident,batch)).fetchone()
    if not row:raise HTTPException(404,'Запись не найдена')
    return jsonable_encoder(row)


@router.post('/api/workspaces/{ws}/balance/companies/{ident}/batches')
def save(ws:int,ident:int,body:BatchIn,u=Depends(current_user),c=Depends(conn)):
    valid_day(body.day)
    try: bid,added=b.save_batch(c,u,ws,ident,body.kind,body.label,body.day,body.payload,body.request_key,body.shop_id,body.previous_id)
    except ValueError as e:raise HTTPException(400,str(e)) from None
    if added:_audit(c,u,ws,'balance/snapshot',{'id':bid,'company':ident,'kind':body.kind,'day':str(body.day)})
    c.commit();return {'id':bid,'added':added}


@router.get('/api/workspaces/{ws}/balance/template/{kind}')
def template(ws:int,kind:Literal['stock','assets','settlement'],u=Depends(current_user),c=Depends(conn)):
    b.scope(c,u,ws)
    return Response(balance_excel.template(kind),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':f'attachment; filename="balance-{kind}.xlsx"'})


@router.post('/api/workspaces/{ws}/balance/companies/{ident}/preview/{kind}')
async def preview(ws:int,ident:int,kind:Literal['stock','assets','settlement'],request:Request,u=Depends(current_user),c=Depends(conn)):
    b.company(c,u,ws,ident,True)
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>5*1024*1024:raise HTTPException(413,'Файл больше 5 МБ')
        chunks.append(chunk)
    raw=b''.join(chunks)
    from starlette.concurrency import run_in_threadpool
    try: data=await run_in_threadpool(balance_excel.parse,raw,kind)
    except ValueError as e:raise HTTPException(400,str(e)) from None
    except Exception:raise HTTPException(400,'Не удалось прочитать файл. Используйте XLSX-шаблон') from None
    return jsonable_encoder(data)
