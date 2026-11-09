"""Fail-closed PreToolUse guard for a personal app job. No host tools."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / 'data/personal-ai/jobs'
CONTROL = ROOT / 'data/personal-ai/control'


def check(event):
    folder = Path(event.get('cwd','')).resolve(strict=True)
    if folder.parent != JOBS.resolve(strict=True) or not folder.name.startswith('job-'):
        raise ValueError('Неизвестная задача личного ИИ.')
    manifest = CONTROL / (folder.name + '.json')
    if manifest.is_symlink():
        raise ValueError('Некорректное описание задачи.')
    meta = json.loads(manifest.read_text())
    tool = event.get('tool_name','').split('.')[-1]
    if meta['mode'] == 'text' and tool in ('ais_read_dossier','ais_search_dossier'):
        return
    if meta['mode'] != 'image' or tool not in ('imagegen','image_gen'):
        raise ValueError('Инструмент недоступен в личном анализе.')
    args = event.get('tool_input') or {}
    if not isinstance(args,dict) or args.get('num_last_images_to_include') or args.get('referenced_image_paths') != list(meta['refs']):
        raise ValueError('Используйте только исходные фотографии этого задания.')
    for name, digest in meta['refs'].items():
        p = Path(name)
        if p.is_symlink() or p.parent != folder or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError('Исходные фотографии изменились.')
    # The model cannot write CONTROL. A second image call is rejected atomically.
    fd = os.open(CONTROL/(folder.name+'.image-started'), os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    os.close(fd)


if __name__ == '__main__':
    try:
        check(json.load(sys.stdin))
    except Exception:
        print('Личный ИИ: действие не соответствует разрешённой задаче.',file=sys.stderr)
        sys.exit(2)
