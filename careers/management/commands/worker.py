import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from careers.services.queue import claim, execute


class Command(BaseCommand):
    help = 'Run the durable discovery / hosted-AI task worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Drain queued tasks and exit')
        parser.add_argument('--poll', type=float, default=2)

    def handle(self, *args, **options):
        self.stdout.write('JobSearch worker is ready. Ctrl+C to stop.')
        try:
            while True:
                close_old_connections()
                task = claim()
                if task:
                    ok = execute(task)
                    self.stdout.write(f'{task.kind}: {"completed" if ok else "failed"}')
                elif options['once']:
                    return
                else:
                    time.sleep(max(.5, options['poll']))
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped.')
