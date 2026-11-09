"""Set up a separate local Codex profile; login stays inside official Codex."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stometric.owner_paths import BASE,PROFILE,JOBS,CONTROL,POLICY,binary,environment,policy_command
from stometric.owner_rpc import AppServer

class SetupError(RuntimeError):
    pass

def configuration():
    return '''# Personal AI platform profile. No developer tools or shared API credentials.
default_permissions = "personal"
approval_policy = "never"
web_search = "disabled"
project_doc_max_bytes = 0

[features]
image_generation = true

[permissions.personal]
extends = ":read-only"
[permissions.personal.filesystem]
":root" = "deny"
":workspace_roots" = "read"
[permissions.personal.network]
enabled = false

[[hooks.PreToolUse]]
matcher = "*"
[[hooks.PreToolUse.hooks]]
type = "command"
command = '''+json.dumps(policy_command())+'''
timeout = 10
'''


async def setup():
    exe=binary()
    if not exe:raise SetupError('Сначала установите официальный Codex CLI.')
    if any(c in str(POLICY) for c in ' \n\r\t"\'`$;'):
        raise SetupError('Путь установки не должен содержать пробелы или специальные символы shell.')
    for folder in (BASE,PROFILE,JOBS,CONTROL):
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        if folder.is_symlink():raise SetupError('Профиль не должен находиться по символической ссылке.')
        folder.chmod(0o700)
    target=PROFILE/'config.toml'
    if target.is_symlink():raise SetupError('Файл конфигурации не должен быть ссылкой.')
    if target.exists():
        current=tomllib.loads(target.read_text())
        # Only the installer-owned profile is supported; never rewrite another config.
        current.get('hooks',{}).pop('state',None)
        expected=tomllib.loads(configuration())
        if current!=expected:raise SetupError('Профиль отличается от шаблона. Проверьте изменения вручную; файл не перезаписан.')
    else:
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as out:out.write(configuration())
    rpc=AppServer([exe,'app-server'],env=environment())
    try:
        await rpc.start(str(JOBS))
        hooks=await rpc.call('hooks/list',{'cwds':[str(JOBS)]})
        all_hooks=[h for g in hooks.get('data',[]) for h in g.get('hooks',[])]
        guards=[h for h in all_hooks if h.get('eventName')=='preToolUse' and h.get('command')==policy_command()]
        if len(guards)!=1 or len(all_hooks)!=1 or not guards[0].get('currentHash'):
            raise SetupError('Codex не подтвердил единственный защитный hook.')
        h=guards[0]
        # Trust exactly this shipped guard. No generic approval hooks are added.
        text=configuration()+'\n[hooks.state.'+json.dumps(h['key'])+']\ntrusted_hash = '+json.dumps(h['currentHash'])+'\nenabled = true\n'
        tomllib.loads(text)
        tmp=PROFILE/'config.setup.tmp'
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as out:out.write(text)
        os.replace(tmp,target)
    finally:await rpc.close()
    print('Профиль и защита настроены. Далее: login, check и включение VIP в админке.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('setup','login','check'))
    args=p.parse_args()
    if args.action=='setup':asyncio.run(setup());return
    if args.action=='login':
        if not binary() or not (PROFILE/'config.toml').is_file():raise SetupError('Сначала выполните setup.')
        # Interactive official login. Never read, copy or print its stored tokens.
        subprocess.run([binary(),'login','--device-auth'],env=environment(),check=True)
        return
    from stometric.owner_runtime import probe
    result=probe();print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result.get('text_ready'):sys.exit(1)


if __name__=='__main__':
    try:main()
    except SetupError as e:
        print(str(e),file=sys.stderr);sys.exit(1)
    except Exception:
        print('Настройка личного Codex не завершена. Секреты не выводились.',file=sys.stderr);sys.exit(1)
