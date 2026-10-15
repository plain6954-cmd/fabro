"""Compare table counts and integrity of the isolated synthetic SQLite pair."""

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKTREES = (ROOT, ROOT.parent / 'fast-navigation-baseline')


def inspect(checkout):
    checkout = checkout.resolve()
    if (checkout.name not in {'fast-navigation-htmx', 'fast-navigation-baseline'}
            or checkout.parent.name != 'output' or not (checkout / '.git').is_file()):
        raise RuntimeError('Refusing a non-disposable worktree.')
    path = checkout / 'output' / 'navigation-synthetic.sqlite3'
    if not path.is_file():
        raise RuntimeError(f'Missing synthetic DB: {path}')
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError(f'SQLite integrity failed: {path}')
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts = {table: connection.execute(
            f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        pages = connection.execute('PRAGMA page_count').fetchone()[0]
        freelist = connection.execute('PRAGMA freelist_count').fetchone()[0]
    return {'bytes': path.stat().st_size, 'pages': pages, 'free_pages': freelist,
            'counts': counts}


def main():
    feature, baseline = (inspect(checkout) for checkout in WORKTREES)
    differences = {table: {'feature': feature['counts'].get(table),
                           'baseline': baseline['counts'].get(table)}
                   for table in sorted(feature['counts'].keys() | baseline['counts'].keys())
                   if feature['counts'].get(table) != baseline['counts'].get(table)}
    print(json.dumps({'feature': {key: feature[key] for key in ('bytes', 'pages', 'free_pages')},
                      'baseline': {key: baseline[key] for key in ('bytes', 'pages', 'free_pages')},
                      'count_differences': differences}, indent=2))


if __name__ == '__main__':
    main()
