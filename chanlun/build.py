"""Assemble the standalone indicator; no Pine imports or generated placeholders."""
from pathlib import Path
root = Path(__file__).resolve().parent
modules = sorted((root / 'modules').glob('[0-9][0-9]_*.pine'))
text = '\n\n'.join(p.read_text().rstrip() for p in modules) + '\n'
assert text.count('//@version=6') == 1
assert 'f_fullSelfTest() =>' in text
output = root / 'Chan_Theory_Complete.pine'
output.write_text(text)
print(f'{output}: {len(text.splitlines())} lines, {len(text.encode())} bytes')
