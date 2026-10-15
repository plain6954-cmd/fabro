"""Populate the isolated navigation-performance SQLite database."""

import json

from django.core.management.base import BaseCommand

from scripts.synthetic_data import seed


class Command(BaseCommand):
    help = 'Idempotently seed only the isolated navigation-synthetic.sqlite3 database.'

    def handle(self, *args, **options):
        result = seed()
        self.stdout.write(json.dumps(result, indent=2))
