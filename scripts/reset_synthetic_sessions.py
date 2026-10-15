"""Clear only benchmark login sessions in both disposable synthetic databases."""

import sqlite3
from pathlib import Path

from verify_synthetic_pair import WORKTREES, inspect


def main():
    inspected = [inspect(checkout) for checkout in WORKTREES]
    domains = [{table: count for table, count in item['counts'].items()
                if table != 'django_session'} for item in inspected]
    if domains[0] != domains[1]:
        raise RuntimeError('Fixture table counts differ; refusing benchmark reset.')
    for checkout in WORKTREES:
        path = checkout / 'output' / 'navigation-synthetic.sqlite3'
        with sqlite3.connect(path) as connection:
            connection.execute('DELETE FROM django_session')
            connection.commit()
            connection.execute('VACUUM')
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError(f'SQLite integrity failed: {path}')
        print(f'{path}: {Path(path).stat().st_size} bytes, no login sessions')


if __name__ == '__main__':
    main()
