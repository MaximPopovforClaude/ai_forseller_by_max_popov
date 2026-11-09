"""Build a site-bound extension in memory, without changing release files."""
import html
import io
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import zipfile

VERSION = '0.2.9'
FILES = ('manifest.json','bg.js','popup.js','popup.html','seller.js','wb.js','panel.css','brand.svg','README.md')


class ExtensionConfigError(ValueError):
    pass


def origin(value):
    message = 'Для скачивания плагина задайте реальный HTTPS-адрес своей платформы в SITE_URL и перезапустите сайт.'
    if not isinstance(value,str) or value != value.strip() or re.search(r'[\s\\\x00-\x1f\x7f]',value):
        raise ExtensionConfigError(message)
    try:
        u=urlsplit(value)
        host=(u.hostname or '').encode('idna').decode().lower()
        port=u.port
    except (ValueError,UnicodeError):
        raise ExtensionConfigError(message) from None
    if (u.scheme!='https' or not host or u.username is not None or u.password is not None
            or u.path not in ('','/') or u.query or u.fragment or port==0):
        raise ExtensionConfigError(message)
    if host=='localhost' or host.endswith('.localhost') or host.endswith('.'):
        raise ExtensionConfigError(message)
    if any(host==h or host.endswith('.'+h) for h in ('example.org','example.com','example.net')):
        raise ExtensionConfigError(message)
    try:
        addr=ipaddress.ip_address(host)
        if not addr.is_global:raise ExtensionConfigError(message)
        if addr.version==6:host='['+host+']'
    except ValueError as error:
        if isinstance(error,ExtensionConfigError):raise
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '.' not in host:
            raise ExtensionConfigError(message) from None
        if any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in host.split('.')):
            raise ExtensionConfigError(message)
    return 'https://'+host+(':'+str(port) if port and port!=443 else '')


def configured_files(directory, site):
    site=origin(site)
    directory=Path(directory)
    result={}
    for name in FILES:
        p=directory/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size>2*1024*1024:
            raise ExtensionConfigError('Файлы плагина неполны. Обновите сборку платформы.')
        result[name]=p.read_bytes()
    manifest=json.loads(result['manifest.json'])
    manifest.update(version=VERSION,host_permissions=[site+'/*','https://*.wildberries.ru/*'])
    manifest['description']='AI-100metric by Max Popov: данные вашей платформы и отчёты Wildberries.'
    result['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    text=result['bg.js'].decode()
    pattern=r'^const API = ("(?:[^"\\]|\\.)*");'
    old=re.findall(pattern,text,re.M)
    if len(old)!=1:raise ExtensionConfigError('Не найден адрес API плагина. Обновите сборку.')
    text=re.sub(pattern,lambda _: 'const API = '+json.dumps(site)+';',text,count=1,flags=re.M)
    old_host=urlsplit(json.loads(old[0])).netloc
    if old_host:text=text.replace('Запросы к '+old_host,'Запросы к '+urlsplit(site).netloc)
    result['bg.js']=text.encode()
    text,count=re.subn(r'(<span id="platform-host">)[^<]*(</span>)',lambda m:m[1]+html.escape(site)+m[2],result['popup.html'].decode())
    if count!=1:raise ExtensionConfigError('Не найден адрес сайта в окне плагина. Обновите сборку.')
    result['popup.html']=text.encode()
    text=re.sub(r'"Полностью — [^"\n]* → вкладка «Полки»\."',lambda _:json.dumps('Полностью — '+urlsplit(site).netloc+' → вкладка «Полки».',ensure_ascii=False),result['wb.js'].decode())
    result['wb.js']=text.encode()
    return result


def archive(directory, site):
    files=configured_files(directory,site)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as out:
        for name,content in files.items():out.writestr('seller-analytics-plugin/'+name,content)
    return buf.getvalue()
