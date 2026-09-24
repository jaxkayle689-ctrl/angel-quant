"""Build a source-only distribution; never include local credentials or caches."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', '.env.example', 'README.md', 'pyproject.toml',
              'requirements.txt', 'requirements-build.txt', 'requirements-dev.txt'}
TREES = {'src', 'frontend', 'tests', 'scripts', 'docs', 'chanlun', 'packaging', 'experiments'}
SKIP = {'__pycache__', 'node_modules', '.git', '.pytest_cache', 'dist', 'results'}
SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                    r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}|'
                    r'https://open\.feishu\.cn/open-apis/bot/v2/hook/[a-f0-9-]{32,}|'
                    r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')


def include(path):
    relative = path.relative_to(ROOT)
    parts = relative.parts
    if path.is_symlink() or any(p in SKIP or p.endswith(('.egg-info', '_results')) for p in parts):
        return False
    if path.name == '.DS_Store' or path.name.startswith('.env') and path.name != '.env.example':
        return False
    if path.suffix in {'.pyc', '.pyo', '.tsbuildinfo', '.log', '.db', '.sqlite', '.pem', '.key'}:
        return False
    if len(parts) == 1:
        return path.name in ROOT_FILES
    if parts[0] not in TREES:
        return False
    if parts[0] == 'experiments':
        return path.suffix in {'.py', '.md', '.pine'} or path.name in {'config.json', 'martingale_config.json'}
    return True


def main():
    files = sorted(p for p in ROOT.rglob('*') if p.is_file() and include(p))
    prepared = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        try:
            content = data.decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            prepared.append((path, relative, data))
            continue
        if path.name in {'config.json', 'martingale_config.json'}:
            def check(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key.lower() in {'key', 'secret', 'password', 'token', 'api_key', 'api_secret', 'username', 'jwt_secret_key', 'ws_token', 'chat_id'}:
                            value[key] = ''
                        check(item)
                elif isinstance(value, list):
                    for item in value:
                        check(item)
            config = json.loads(content)
            check(config)
            if isinstance(config.get('api_server'), dict):
                config['api_server']['enabled'] = False
            content = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
            data = content.encode('utf-8')
            relative = relative.removesuffix('.json') + '.example.json'
        if SECRET.search(content):
            raise SystemExit('Possible credential; package aborted: ' + str(path.relative_to(ROOT)))
        prepared.append((path, relative, data))
    destination = ROOT / 'output' / 'git-release'
    destination.mkdir(parents=True, exist_ok=True)
    name = 'angel-quant-source-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    archive = destination / (name + '.zip')
    manifest = {'archive': archive.name, 'files': [], 'excluded': ['credentials', 'dependencies', 'builds', 'backtest data and results']}
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
        for path, relative, data in prepared:
            info = zipfile.ZipInfo.from_file(path, 'angel-quant/' + relative)
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data)
            manifest['files'].append({'path': relative, 'bytes': len(data),
                                      'sha256': hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(archive) as output:
        assert output.testzip() is None
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.sha256').write_text(digest + '  ' + archive.name + '\n')
    archive.with_suffix('.manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'files': len(files), 'bytes': archive.stat().st_size, 'sha256': digest}, ensure_ascii=False))


if __name__ == '__main__':
    main()
