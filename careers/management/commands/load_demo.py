from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from careers.services.collection import load_demo_inventory

class Command(BaseCommand):
    help = 'Load clearly labelled fictional postings for a mentor demonstration.'
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError('Set DEMO_MODE=true before loading fictional demo jobs.')
        count = load_demo_inventory()
        self.stdout.write(f'Demo inventory ready ({count} new jobs). Create your own account in the browser.')
