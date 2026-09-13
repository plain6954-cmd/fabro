"""Inventory tracked sources and check Python/template syntax offline."""
import ast
from collections import Counter
import json
from pathlib import Path
import subprocess
import verify_offline
from django.template import engines

root = Path(__file__).resolve().parent.parent
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
counts = Counter()
checked = []
failures = []
for name in filter(None, paths):
    path = root / name
    suffix = path.suffix.lower()
    counts[suffix or '(no extension)'] += 1
    # Do not load secrets, database files, stored media, or deployment settings.
    if name == 'fabro_leather/settings.py' or path.name.startswith('.env'):
        continue
    if suffix == '.py':
        try:
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=name)
            checked.append(name)
        except (SyntaxError, UnicodeError) as error:
            failures.append({'file': name, 'error': str(error)})
    elif '/templates/' in name and suffix == '.html':
        try:
            engines['django'].from_string(path.read_text(encoding='utf-8'))
            checked.append(name)
        except Exception as error:
            failures.append({'file': name, 'error': str(error)})

report = {'tracked_files': sum(counts.values()), 'extensions': dict(counts),
          'syntax_checked': checked, 'failures': failures}
output_directory = root / 'scratch' / 'offline-audit'
output_directory.mkdir(parents=True, exist_ok=True)
(output_directory / 'offline-source-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'tracked_files': report['tracked_files'], 'syntax_checked': len(checked), 'failures': failures}))
raise SystemExit(bool(failures))
