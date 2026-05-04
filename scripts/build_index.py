"""Rebuild web/data/index.json — list of available daily JSON dates, newest first."""
import json
from pathlib import Path

files = sorted(
    [f.stem for f in Path('web/data').glob('*.json') if f.stem != 'index'],
    reverse=True,
)
Path('web/data/index.json').write_text(json.dumps(files), encoding='utf-8')
print('Dates indexed:', files[:5])
