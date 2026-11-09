"""Local installation owner configures personal AI; no shared subscription login."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictInt, Field
from .web import current_user, conn, _audit
from . import owner_ai, owner_runtime

router = APIRouter()


def admin(u):
    if not u.get('is_superadmin') or not u.get('is_active'):
        raise HTTPException(403, 'Нужен владелец установки.')


@router.get('/api/admin/personal-ai')
def status(u=Depends(current_user), c=Depends(conn)):
    admin(u)
    cfg = owner_ai.settings(c)
    if cfg.get('owner_user_id') not in (None, u['id']):
        raise HTTPException(403, 'Настройки личного ИИ принадлежат другому владельцу.')
    workspaces = c.execute('''SELECT w.id,w.name FROM workspaces w JOIN memberships m ON m.workspace_id=w.id
        WHERE m.user_id=%s AND m.role='owner' AND m.shop_ids IS NULL ORDER BY w.id''', (u['id'],)).fetchall()
    shops = c.execute('''SELECT a.id,a.title,a.name,a.workspace_id FROM accounts a JOIN memberships m ON m.workspace_id=a.workspace_id
        WHERE m.user_id=%s AND m.role='owner' AND m.shop_ids IS NULL AND a.is_active AND a.archived_at IS NULL
        ORDER BY a.id''', (u['id'],)).fetchall()
    return {'config':cfg,'workspaces':workspaces,'shops':shops}


@router.post('/api/admin/personal-ai/check')
def check(u=Depends(current_user), c=Depends(conn)):
    admin(u)
    if owner_ai.settings(c).get('owner_user_id') not in (None, u['id']):
        raise HTTPException(403, 'Личный ИИ принадлежит другому владельцу.')
    return owner_runtime.probe()


class ConfigIn(BaseModel):
    workspace_id: StrictInt
    shop_ids: list[StrictInt] = Field(max_length=200)
    enabled: bool


@router.put('/api/admin/personal-ai')
def configure(body: ConfigIn, u=Depends(current_user), c=Depends(conn)):
    admin(u)
    # The client cannot claim that login, isolation or image capability succeeded.
    if owner_ai.settings(c).get('owner_user_id') not in (None, u['id']):
        raise HTTPException(403, 'Личный ИИ принадлежит другому владельцу.')
    if not owner_ai.owns(c, body.workspace_id, u['id']):
        raise HTTPException(403, 'Выберите свой кабинет.')
    readiness = owner_runtime.probe() if body.enabled else {}
    cfg = owner_ai.save(c,u['id'],body.workspace_id,body.shop_ids,body.enabled,readiness)
    _audit(c,u,body.workspace_id,'personal-ai/configure',{'enabled':body.enabled,'shop_ids':cfg['shop_ids']})
    c.commit()
    return {'ok':True,'config':cfg}
