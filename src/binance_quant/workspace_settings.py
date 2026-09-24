from __future__ import annotations

import base64
import json
import threading
from pathlib import Path


class WorkspaceSettings:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / 'workspace_settings.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {'names': {}, 'deleted': [], 'assets': [], 'reports': {}}
            return json.loads(self.path.read_text(encoding='utf-8'))

    def update(self, **changes):
        with self.lock:
            data = self.read()
            data.update(changes)
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)
            return data

    def image(self, kind, data_url):
        if kind not in ('icon', 'background'):
            raise ValueError('图片类型无效')
        if not data_url:
            return self.update(**{kind: None})
        header, encoded = data_url.split(',', 1)
        if header not in ('data:image/png;base64', 'data:image/jpeg;base64'):
            raise ValueError('请选择 PNG 或 JPG 图片')
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('图片不能超过 8 MB')
        if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):
            raise ValueError('图片内容无效')
        return self.update(**{kind: data_url})
