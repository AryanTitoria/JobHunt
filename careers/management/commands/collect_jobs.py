from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from careers.services.collection import collect_inventory
from careers.services.matching import refresh_matches

class Command(BaseCommand):
    help = 'Collect shared postings and refresh all user matches (schedule hourly/daily).'

    def handle(self, *args, **options):
        result = collect_inventory()
        for user in get_user_model().objects.filter(is_active=True):
            refresh_matches(user)
        self.stdout.write(f"Observed {result['jobs']} jobs from {result['sources']} sources; {len(result['errors'])} warnings.")
