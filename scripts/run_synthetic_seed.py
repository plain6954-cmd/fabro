"""Run the shared synthetic seeder inside either approved FABRO worktree."""

import argparse
import json
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', required=True, type=Path)
    parser.add_argument('--existing-local-db', action='store_true',
                        help='Seed the feature worktree db.sqlite3 without replacing existing users.')
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    if Path.cwd().resolve() != checkout:
        raise RuntimeError('Run this script with the selected worktree as the working directory.')
    sys.path.insert(0, str(SCRIPT_DIR))
    sys.path.insert(0, str(checkout))
    os.environ['DJANGO_SETTINGS_MODULE'] = ('local_existing_fixture_settings'
                                            if args.existing_local_db else 'synthetic_perf_settings')
    from synthetic_perf_settings import allowed_worktree
    if not allowed_worktree(checkout):
        raise RuntimeError('Unapproved worktree.')
    import django
    django.setup()
    from synthetic_data import seed
    print(json.dumps(seed(), indent=2))


if __name__ == '__main__':
    main()
